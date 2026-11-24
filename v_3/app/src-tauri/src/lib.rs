//! Caja V3: la capa de Tauri sobre el núcleo (`v_3/nucleo`).
//!
//! Aquí solo hay comandos que traducen entre la vista web y el núcleo; las reglas (carrito,
//! cobro, ventas, catálogo) viven en el núcleo y están probadas contra la v2.
//!
//! **Base de datos:** la v3 tiene su PROPIA base, con su esquema (`nucleo::esquema`); los datos de
//! la v2 se importan con `cargo run --bin importar_v2` (en `v_3/nucleo`). Ruta (D9, sin rutas
//! fijas): `CAJA_DB` si está definida; si no, `ventas.db` en la carpeta de datos de la app que da el
//! sistema (`~/.local/share/local.sistemaventas.caja/` en Linux); solo en desarrollo, si esa no
//! existe, `datos/ventas_v3.db` del prototipo. **Nunca abre una base de la v2:** ni la ruta real
//! (`v_2/share/ventas.db`) ni ninguna otra con su esquema (el núcleo se niega a migrarla).

use std::path::{Path, PathBuf};
use std::sync::Mutex;

use nucleo::caja::{Autorizacion, EstadoCodigo};
use nucleo::{Base, Carrito, Cobro, DatosUsuario, FilaVentas, Momento, Producto};
use tauri::Emitter;
use serde::{Deserialize, Serialize};
use tauri::Manager;

/// Estado de la base: abierta, o el motivo por el que no se pudo abrir (se muestra en la caja).
struct Estado {
    ruta: PathBuf,
    base: Result<Base, String>,
    /// La sesión de esta ejecución (sesiones_sistema) y su usuario. Lo que se registra la lleva.
    sesion: Option<Sesion>,
}

#[derive(Clone)]
struct Sesion {
    id: i64,
    usuario_id: i64,
    usuario: String,
    /// El turno de caja que tomó esta ejecución (D8). Si deja de ser el vigente, otra caja lo tomó.
    turno: i64,
}

/// Cada cuánto se comprueba que esta caja sigue teniendo el turno (D8, D20).
const VIGILANCIA_TURNO: std::time::Duration = std::time::Duration::from_secs(3);
/// Texto con el que la vista reconoce que falta el código de autorización.
const PIDE_CODIGO: &str = "PIDE_CODIGO";

/// Cada cuánto se registra el latido de la sesión (como la v2).
const LATIDO: std::time::Duration = std::time::Duration::from_secs(60);

type Compartido = Mutex<Estado>;

#[derive(Serialize)]
struct InfoBase {
    ruta: String,
    productos: usize,
    codigos: usize,
    usuario: Option<String>,
    sesion_id: Option<i64>,
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
    // Solo en desarrollo: la base del prototipo, importada de una copia de la v2 (ver scripts/).
    PathBuf::from(concat!(env!("CARGO_MANIFEST_DIR"), "/../datos/ventas_v3.db"))
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
            "No hay base de la v3 en {}. Créala importando una copia de la v2: \
             scripts/copiar_base_real.py (en la caja) o scripts/crear_base_demo.py (fuera), y luego \
             `cargo run --bin importar_v2 -- datos/ventas_copia.db datos/ventas_v3.db` en v_3/nucleo.",
            ruta.display()
        ));
    }
    let base = Base::abrir_v3(ruta).map_err(|e| format!("No se pudo abrir {}: {e}", ruta.display()))?;
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

/// La sesión de esta caja, solo si su turno sigue vigente (D8: antes de cada acción con efecto).
fn sesion_con_turno(estado: &tauri::State<'_, Compartido>) -> Result<Sesion, String> {
    let e = estado.lock().map_err(|e| e.to_string())?;
    let sesion = e.sesion.clone().ok_or("No hay sesión abierta; vuelve a abrir la caja.")?;
    match &e.base {
        Ok(b) if b.turno_vigente(sesion.turno).map_err(|e| e.to_string())? => Ok(sesion),
        Ok(_) => Err("Otra caja tomó el turno: esta caja ya no puede registrar nada.".into()),
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
    let (ruta, sesion) = {
        let e = estado.lock().map_err(|e| e.to_string())?;
        (e.ruta.display().to_string(), e.sesion.clone())
    };
    con_base(&estado, |b| {
        Ok(InfoBase {
            usuario: sesion.as_ref().map(|s| s.usuario.clone()),
            sesion_id: sesion.as_ref().map(|s| s.id),
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
/// v2) y el total se calcula aquí, no en la vista. `recibido` vacío = pago exacto. `sin_ticket`
/// (D15): cobro rápido, recibido = total, cambio 0, no imprime ticket pero el cajón se abre igual.
#[tauri::command]
fn cobrar(estado: tauri::State<'_, Compartido>, items: Vec<Entrada>, recibido: String, sin_ticket: bool) -> Result<VentaRegistrada, String> {
    let mut carrito = Carrito::nuevo();
    for i in &items {
        if !carrito.agregar(&i.producto, i.precio, i.cantidad) {
            return Err(format!("Un producto del carrito está incompleto: {:?}.", i.producto));
        }
    }
    if carrito.esta_vacio() {
        return Err("El carrito está vacío.".into());
    }
    let cobro = if sin_ticket { Cobro::exacto(carrito.total()) } else { Cobro::con_texto(carrito.total(), &recibido).map_err(|e| e.to_string())? };
    let sesion = sesion_con_turno(&estado)?;
    con_base(&estado, |b| {
        let momento = Momento::ahora();
        let registrada = if sin_ticket {
            b.registrar_venta_sin_ticket(&carrito.filas, &momento, Some(sesion.id))
        } else {
            b.registrar_venta(&carrito.filas, cobro.recibido, cobro.cambio, &momento, Some(sesion.id))
        };
        let venta_id = registrada.map_err(|e| e.to_string())?.ok_or("El carrito está vacío.")?;
        // El cobro abre el cajón (con el ticket). Fase 3: abrirlo de verdad y registrar después.
        // D23: también entra al registro de aperturas.
        b.registrar_apertura(Autorizacion::Venta, Some(venta_id), &momento, Some(sesion.id)).map_err(|e| e.to_string())?;
        Ok(VentaRegistrada { venta_id, total: cobro.total, recibido: cobro.recibido, cambio: cobro.cambio })
    })
}

#[derive(Serialize)]
struct EstadoCaja {
    permisos: Vec<&'static str>,
    /// Cómo se abriría el cajón ahora: permiso, ventana_diaria o codigo.
    como_abrir: &'static str,
    codigo: EstadoCodigo,
    /// Tiene "abrir caja sin límite": puede (y debe, si falta) poner el código.
    puede_poner_codigo: bool,
}

/// Lo que la vista necesita para el botón "Abrir caja" y el código (D21, D23).
#[tauri::command]
fn estado_caja(estado: tauri::State<'_, Compartido>) -> Result<EstadoCaja, String> {
    let sesion = estado.lock().map_err(|e| e.to_string())?.sesion.clone().ok_or("No hay sesión abierta.")?;
    con_base(&estado, |b| {
        let permisos = b.permisos(sesion.usuario_id).map_err(|e| e.to_string())?;
        Ok(EstadoCaja {
            puede_poner_codigo: permisos.contains(&nucleo::caja::Permiso::AbrirCajaSinLimite),
            permisos: permisos.iter().map(|p| p.clave()).collect(),
            como_abrir: b.como_abrir(sesion.usuario_id, &Momento::ahora().fecha).map_err(|e| e.to_string())?.clave(),
            codigo: b.estado_codigo().map_err(|e| e.to_string())?,
        })
    })
}

/// "Abrir caja" (y Intro con el carrito vacío, D23). Si hace falta código y no viene, responde
/// `PIDE_CODIGO`. Fase 3: el cajón se abre de verdad antes de registrar; hoy se simula.
#[tauri::command]
fn abrir_caja(estado: tauri::State<'_, Compartido>, codigo: Option<String>) -> Result<&'static str, String> {
    let sesion = sesion_con_turno(&estado)?;
    con_base(&estado, |b| {
        let momento = Momento::ahora();
        let autorizacion = b.como_abrir(sesion.usuario_id, &momento.fecha).map_err(|e| e.to_string())?;
        if autorizacion == Autorizacion::Codigo {
            // Si no hay código disponible, ninguno va a servir: se avisa sin pedirlo.
            match b.estado_codigo().map_err(|e| e.to_string())? {
                EstadoCodigo::SinCodigo => return Err(nucleo::caja::ErrorCaja::SinCodigo.to_string()),
                EstadoCodigo::Usado { usado_en, .. } => {
                    return Err(format!("{} (Se usó el {usado_en}.)", nucleo::caja::ErrorCaja::CodigoUsado));
                }
                EstadoCodigo::Disponible => {}
            }
            let Some(codigo) = codigo.filter(|c| !c.trim().is_empty()) else { return Err(PIDE_CODIGO.into()) };
            b.usar_codigo(&codigo, &momento, Some(sesion.id)).map_err(|e| e.to_string())?;
        }
        b.registrar_apertura(autorizacion, None, &momento, Some(sesion.id)).map_err(|e| e.to_string())?;
        Ok(autorizacion.clave())
    })
}

/// Los botones de la columna derecha para el usuario de la sesión (P1: configurables, como la v2).
#[tauri::command]
fn botones(estado: tauri::State<'_, Compartido>) -> Result<Vec<nucleo::botones::Boton>, String> {
    let sesion = estado.lock().map_err(|e| e.to_string())?.sesion.clone().ok_or("No hay sesión abierta.")?;
    con_base(&estado, |b| b.botones_de(sesion.usuario_id).map_err(|e| e.to_string()))
}

/// Pone un código de autorización nuevo (solo con "abrir caja sin límite"; el núcleo lo comprueba).
#[tauri::command]
fn poner_codigo(estado: tauri::State<'_, Compartido>, codigo: String) -> Result<(), String> {
    let sesion = sesion_con_turno(&estado)?;
    con_base(&estado, |b| b.poner_codigo(sesion.usuario_id, &codigo, &Momento::ahora(), Some(sesion.id)).map_err(|e| e.to_string()))
}

/// Abre la sesión de esta ejecución con el usuario del sistema (el mismo que reconoce la v2).
fn abrir_sesion(base: &mut Base) -> Result<Sesion, String> {
    let datos = DatosUsuario::del_sistema();
    let (usuario_id, _nuevo) = base.asegurar_usuario(&datos).map_err(|e| e.to_string())?;
    let momento = Momento::ahora();
    let id = base
        .iniciar_sesion(usuario_id, &momento, Some(std::process::id() as i64), Some("caja v3 (prototipo)"))
        .map_err(|e| e.to_string())?;
    // D8: el último que abre se queda con la caja.
    let turno = base.tomar_turno(Some(id), &momento).map_err(|e| e.to_string())?;
    Ok(Sesion { id, usuario_id, usuario: datos.nombre_usuario, turno })
}

/// D8/D20/D23: cada `VIGILANCIA_TURNO` comprueba que esta caja sigue teniendo el turno. Si otra lo
/// tomó, cierra la sesión como "desplazada", avisa a la vista y cierra la app entera.
fn vigilar_turno(app: tauri::AppHandle) {
    std::thread::spawn(move || loop {
        std::thread::sleep(VIGILANCIA_TURNO);
        let estado = app.state::<Compartido>();
        let perdida = {
            let Ok(mut e) = estado.lock() else { return };
            let Some(sesion) = e.sesion.clone() else { return };
            let Ok(base) = &mut e.base else { return };
            match base.turno_vigente(sesion.turno) {
                Ok(true) | Err(_) => None,
                Ok(false) => {
                    let detalle = "desplazada: otra caja tomó el turno";
                    if let Err(error) = base.cerrar_sesion(sesion.id, &Momento::ahora(), Some(detalle), true) {
                        log::warn!("No se pudo cerrar la sesión desplazada {}: {error}", sesion.id);
                    }
                    e.sesion = None;
                    Some(sesion)
                }
            }
        };
        if let Some(sesion) = perdida {
            log::warn!("La sesión {} perdió el turno {}: se cierra la caja.", sesion.id, sesion.turno);
            let _ = app.emit("turno-perdido", ());
            std::thread::sleep(std::time::Duration::from_secs(4));
            app.exit(0);
            return;
        }
    });
}

/// Latido cada `LATIDO` mientras viva la app (hilo de fondo; un fallo solo se anota).
fn iniciar_latido(app: tauri::AppHandle) {
    std::thread::spawn(move || loop {
        std::thread::sleep(LATIDO);
        let estado = app.state::<Compartido>();
        let Ok(mut e) = estado.lock() else { return };
        let Some(sesion) = e.sesion.clone() else { return };
        if let Ok(base) = &mut e.base {
            if let Err(error) = base.latido(sesion.id, &Momento::ahora()) {
                log::warn!("No se pudo registrar el latido de la sesión {}: {error}", sesion.id);
            }
        }
    });
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  let app = tauri::Builder::default()
    .setup(|app| {
      let ruta = ruta_base(app.handle());
      let mut base = abrir(&ruta);
      if let Err(motivo) = &base {
        log::error!("{motivo}");
      }
      let sesion = match &mut base {
        Ok(b) => abrir_sesion(b).map_err(|e| log::error!("No se pudo abrir la sesión: {e}")).ok(),
        Err(_) => None,
      };
      app.manage(Mutex::new(Estado { ruta, base, sesion }));
      iniciar_latido(app.handle().clone());
      vigilar_turno(app.handle().clone());
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
      }
      Ok(())
    })
    .invoke_handler(tauri::generate_handler![buscar_productos, buscar_codigo, info_base, fechas_con_ventas, ventas_del_dia, cobrar, estado_caja, abrir_caja, poner_codigo, botones])
    .build(tauri::generate_context!())
    .expect("error while building tauri application");
  app.run(|app, evento| {
    // Cierre normal: la sesión se cierra como exitosa. Si la app se cae, la sesión queda abierta
    // (sin salida_real ni cerrada_correctamente), y así se distingue una caída de un cierre.
    if let tauri::RunEvent::Exit = evento {
      let estado = app.state::<Compartido>();
      if let Ok(mut e) = estado.lock() {
        if let (Some(sesion), Ok(base)) = (e.sesion.clone(), &mut e.base) {
          if let Err(error) = base.cerrar_sesion(sesion.id, &Momento::ahora(), Some("cierre normal"), true) {
            log::warn!("No se pudo cerrar la sesión {}: {error}", sesion.id);
          }
        }
      }
    }
  });
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
