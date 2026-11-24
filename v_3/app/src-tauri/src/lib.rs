//! Caja V3: la capa de Tauri sobre el núcleo (`v_3/nucleo`).
//!
//! Aquí solo hay comandos que traducen entre la vista web y el núcleo; las reglas (carrito,
//! cobro, ventas, catálogo) viven en el núcleo y están probadas contra la v2.
//!
//! **Base de datos (D9, sin rutas fijas):** `CAJA_DB` si está definida; si no, `ventas.db` en la
//! carpeta de datos de la app que da el sistema (`~/.local/share/local.sistemaventas.caja/` en
//! Linux). Solo en desarrollo, si no existe ninguna de las dos, se usa `datos/ventas_copia.db` del
//! prototipo. **La app se niega a abrir la base real de la v2** (`v_2/share/ventas.db`): mientras
//! la v2 esté en producción, la v3 escribe solo en una copia.

use std::path::{Path, PathBuf};
use std::sync::Mutex;

use nucleo::{Base, Carrito, Cobro, FilaVentas, Momento, Producto};
use serde::{Deserialize, Serialize};
use tauri::Manager;

/// Estado de la base: abierta, o el motivo por el que no se pudo abrir (se muestra en la caja).
struct Estado {
    ruta: PathBuf,
    base: Result<Base, String>,
}

type Compartido = Mutex<Estado>;

#[derive(Serialize)]
struct InfoBase {
    ruta: String,
    productos: usize,
    codigos: usize,
}

#[derive(Serialize)]
struct ProductoConPrecio {
    producto: String,
    precio: f64,
}

#[derive(Deserialize)]
struct Entrada {
    producto: String,
    precio: f64,
    cantidad: i64,
}

#[derive(Serialize)]
struct VentaRegistrada {
    venta_id: i64,
    total: f64,
    recibido: f64,
    cambio: f64,
}

/// La ruta de la base, sin rutas fijas (D9).
fn ruta_base(app: &tauri::AppHandle) -> PathBuf {
    if let Some(ruta) = std::env::var_os("CAJA_DB") {
        return PathBuf::from(ruta);
    }
    let datos = app.path().app_data_dir().map(|d| d.join("ventas.db"));
    if let Ok(ruta) = &datos {
        if ruta.exists() || !cfg!(debug_assertions) {
            return ruta.clone();
        }
    }
    // Solo en desarrollo: la copia del prototipo (scripts/copiar_base_real.py o crear_base_demo.py).
    PathBuf::from(concat!(env!("CARGO_MANIFEST_DIR"), "/../datos/ventas_copia.db"))
}

/// ¿Es la base real de la v2? Mientras la v2 esté en producción, la v3 no la toca.
fn es_base_de_la_v2(ruta: &Path) -> bool {
    let ruta = ruta.canonicalize().unwrap_or_else(|_| ruta.to_path_buf());
    ruta.ends_with("v_2/share/ventas.db")
}

fn abrir(ruta: &Path) -> Result<Base, String> {
    if es_base_de_la_v2(ruta) {
        return Err(format!("{} es la base real de la v2: la v3 solo trabaja sobre una copia.", ruta.display()));
    }
    if !ruta.exists() {
        return Err(format!(
            "No hay base en {}. En la caja: scripts/copiar_base_real.py; fuera de ella: scripts/crear_base_demo.py.",
            ruta.display()
        ));
    }
    let base = Base::abrir(ruta).map_err(|e| format!("No se pudo abrir {}: {e}", ruta.display()))?;
    base.verificar_esquema().map_err(|e| format!("{}: {e}", ruta.display()))?;
    Ok(base)
}

/// Ejecuta `f` con la base abierta, o devuelve por qué no hay base.
fn con_base<T>(estado: &tauri::State<'_, Compartido>, f: impl FnOnce(&mut Base) -> Result<T, String>) -> Result<T, String> {
    let mut estado = estado.lock().map_err(|e| e.to_string())?;
    match &mut estado.base {
        Ok(base) => f(base),
        Err(motivo) => Err(motivo.clone()),
    }
}

/// Productos que coinciden con lo escrito: contienen el texto o empiezan con esas iniciales.
#[tauri::command]
fn buscar_productos(estado: tauri::State<'_, Compartido>, texto: String) -> Result<Vec<Producto>, String> {
    if texto.trim().is_empty() {
        return Ok(Vec::new());
    }
    con_base(&estado, |b| b.buscar_productos(&texto, 8).map_err(|e| e.to_string()))
}

#[tauri::command]
fn buscar_codigo(estado: tauri::State<'_, Compartido>, codigo: String) -> Result<Option<ProductoConPrecio>, String> {
    con_base(&estado, |b| {
        Ok(b.buscar_codigo(&codigo).map_err(|e| e.to_string())?.map(|c| ProductoConPrecio { producto: c.producto, precio: c.precio }))
    })
}

#[tauri::command]
fn info_base(estado: tauri::State<'_, Compartido>) -> Result<InfoBase, String> {
    let ruta = estado.lock().map_err(|e| e.to_string())?.ruta.display().to_string();
    con_base(&estado, |b| {
        Ok(InfoBase {
            ruta,
            productos: b.productos().map_err(|e| e.to_string())?.len(),
            codigos: b.codigos("").map_err(|e| e.to_string())?.len(),
        })
    })
}

/// Hoy y los últimos días con ventas (más reciente primero).
#[tauri::command]
fn fechas_con_ventas(estado: tauri::State<'_, Compartido>) -> Result<Vec<String>, String> {
    let hoy = Momento::ahora().fecha;
    con_base(&estado, |b| {
        let mut dias = b.dias_con_ventas(30).map_err(|e| e.to_string())?;
        if !dias.contains(&hoy) {
            dias.insert(0, hoy);
        }
        Ok(dias)
    })
}

/// VENTAS REALIZADAS de un día. Hoy, desde el último corte de caja (como la hoja de la v2); otro
/// día, el día completo (como VER VENTAS).
#[tauri::command]
fn ventas_del_dia(estado: tauri::State<'_, Compartido>, fecha: String) -> Result<Vec<FilaVentas>, String> {
    let es_hoy = fecha == Momento::ahora().fecha;
    con_base(&estado, |b| b.ventas_del_dia(&fecha, es_hoy).map_err(|e| e.to_string()))
}

/// Cobra el carrito y registra la venta. El carrito se rearma con las reglas del núcleo (las de la
/// v2) y el total se calcula aquí, no en la vista. `recibido` vacío = pago exacto.
#[tauri::command]
fn cobrar(estado: tauri::State<'_, Compartido>, items: Vec<Entrada>, recibido: String) -> Result<VentaRegistrada, String> {
    let mut carrito = Carrito::nuevo();
    for i in &items {
        if !carrito.agregar(&i.producto, i.precio, i.cantidad) {
            return Err(format!("Un producto del carrito está incompleto: {:?}.", i.producto));
        }
    }
    if carrito.esta_vacio() {
        return Err("El carrito está vacío.".into());
    }
    let cobro = Cobro::con_texto(carrito.total(), &recibido).map_err(|e| e.to_string())?;
    con_base(&estado, |b| {
        let venta_id = b
            .registrar_venta(&carrito.filas, cobro.recibido, cobro.cambio, &Momento::ahora(), None)
            .map_err(|e| e.to_string())?
            .ok_or("El carrito está vacío.")?;
        Ok(VentaRegistrada { venta_id, total: cobro.total, recibido: cobro.recibido, cambio: cobro.cambio })
    })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .setup(|app| {
      let ruta = ruta_base(app.handle());
      let base = abrir(&ruta);
      if let Err(motivo) = &base {
        log::error!("{motivo}");
      }
      app.manage(Mutex::new(Estado { ruta, base }));
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
      }
      Ok(())
    })
    .invoke_handler(tauri::generate_handler![buscar_productos, buscar_codigo, info_base, fechas_con_ventas, ventas_del_dia, cobrar])
    .run(tauri::generate_context!())
    .expect("error while building tauri application");
}

#[cfg(test)]
mod pruebas {
  use super::*;

  #[test]
  fn se_niega_a_abrir_la_base_real_de_la_v2() {
    match abrir(Path::new("/home/alguien/sistema_ventas/v_2/share/ventas.db")) {
      Err(error) => assert!(error.contains("base real de la v2"), "{error}"),
      Ok(_) => panic!("abrió la base real de la v2"),
    }
  }
}
