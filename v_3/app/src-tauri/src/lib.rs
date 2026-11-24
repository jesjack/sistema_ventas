//! Caja V3, fase 0: la parte en Rust del prototipo.
//!
//! Solo lee una COPIA de la base de la v2 (`datos/ventas_copia.db`), abierta en modo de solo
//! lectura: el prototipo no puede escribir en ninguna base. Ruta alternativa con `CAJA_DB`.

use std::path::PathBuf;
use std::sync::Mutex;

use rusqlite::{Connection, OpenFlags, OptionalExtension, params};
use serde::Serialize;

struct Base(Mutex<Connection>);

#[derive(Serialize)]
struct ProductoConPrecio {
  producto: String,
  precio: f64,
}

/// Una línea de VENTAS REALIZADAS: el producto vendido con los datos de su venta.
#[derive(Serialize)]
struct LineaVenta {
  venta_id: i64,
  hora: String,
  producto: String,
  precio: f64,
  cantidad: i64,
  subtotal: f64,
  total_venta: f64,
}

#[derive(Serialize)]
struct InfoBase {
  ruta: String,
  productos: i64,
  codigos: i64,
}

fn ruta_base() -> PathBuf {
  std::env::var_os("CAJA_DB")
    .map(PathBuf::from)
    .unwrap_or_else(|| PathBuf::from(concat!(env!("CARGO_MANIFEST_DIR"), "/../datos/ventas_copia.db")))
}

fn abrir_base() -> Result<Connection, String> {
  let ruta = ruta_base();
  Connection::open_with_flags(&ruta, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX)
    .map_err(|e| format!("No se pudo abrir {}: {e}", ruta.display()))
}

fn texto_error(e: rusqlite::Error) -> String {
  e.to_string()
}

/// Escapa `%`, `_` y `\` para usar lo escrito dentro de un LIKE.
fn escapar_like(texto: &str) -> String {
  texto.replace('\\', "\\\\").replace('%', "\\%").replace('_', "\\_")
}

/// Productos del catálogo que contienen lo escrito; primero los que empiezan así.
#[tauri::command]
fn buscar_productos(base: tauri::State<'_, Base>, texto: String) -> Result<Vec<String>, String> {
  let texto = texto.trim();
  if texto.is_empty() {
    return Ok(Vec::new());
  }
  let escapado = escapar_like(texto);
  let conn = base.0.lock().map_err(|e| e.to_string())?;
  let mut consulta = conn
    .prepare_cached(
      "SELECT producto FROM catalogo_autocompletado
       WHERE producto LIKE ?1 ESCAPE '\\'
       ORDER BY (producto LIKE ?2 ESCAPE '\\') DESC, producto
       LIMIT 8",
    )
    .map_err(texto_error)?;
  let filas = consulta
    .query_map(params![format!("%{escapado}%"), format!("{escapado}%")], |fila| fila.get(0))
    .map_err(texto_error)?;
  filas.collect::<Result<Vec<String>, _>>().map_err(texto_error)
}

/// Producto y precio de un código de barras registrado, o nada si no está registrado.
#[tauri::command]
fn buscar_codigo(base: tauri::State<'_, Base>, codigo: String) -> Result<Option<ProductoConPrecio>, String> {
  let conn = base.0.lock().map_err(|e| e.to_string())?;
  conn
    .query_row(
      "SELECT c.producto, r.precio_venta
       FROM codigos_barras_registrados r
       JOIN catalogo_autocompletado c ON c.id = r.producto_id
       WHERE r.codigo_barras = ?1",
      params![codigo.trim()],
      |fila| Ok(ProductoConPrecio { producto: fila.get(0)?, precio: fila.get(1)? }),
    )
    .optional()
    .map_err(texto_error)
}

/// Los últimos días que tienen ventas (más reciente primero).
#[tauri::command]
fn fechas_con_ventas(base: tauri::State<'_, Base>) -> Result<Vec<String>, String> {
  let conn = base.0.lock().map_err(|e| e.to_string())?;
  let mut consulta = conn
    .prepare_cached("SELECT DISTINCT fecha FROM ventas ORDER BY fecha DESC LIMIT 30")
    .map_err(texto_error)?;
  let filas = consulta.query_map([], |fila| fila.get(0)).map_err(texto_error)?;
  filas.collect::<Result<Vec<String>, _>>().map_err(texto_error)
}

/// Lo vendido un día (`AAAA-MM-DD`), en orden de venta.
#[tauri::command]
fn ventas_del_dia(base: tauri::State<'_, Base>, fecha: String) -> Result<Vec<LineaVenta>, String> {
  let conn = base.0.lock().map_err(|e| e.to_string())?;
  let mut consulta = conn
    .prepare_cached(
      "SELECT v.id, v.hora, i.producto, i.precio, i.cantidad, i.subtotal, v.total
       FROM ventas v JOIN venta_items i ON i.venta_id = v.id
       WHERE v.fecha = ?1
       ORDER BY v.hora, v.id, i.id",
    )
    .map_err(texto_error)?;
  let filas = consulta
    .query_map(params![fecha], |f| {
      Ok(LineaVenta {
        venta_id: f.get(0)?,
        hora: f.get(1)?,
        producto: f.get(2)?,
        precio: f.get(3)?,
        cantidad: f.get(4)?,
        subtotal: f.get(5)?,
        total_venta: f.get(6)?,
      })
    })
    .map_err(texto_error)?;
  filas.collect::<Result<Vec<_>, _>>().map_err(texto_error)
}

#[tauri::command]
fn info_base(base: tauri::State<'_, Base>) -> Result<InfoBase, String> {
  let conn = base.0.lock().map_err(|e| e.to_string())?;
  let contar = |tabla: &str| -> Result<i64, String> {
    conn.query_row(&format!("SELECT count(*) FROM {tabla}"), [], |f| f.get(0)).map_err(texto_error)
  };
  Ok(InfoBase {
    ruta: ruta_base().display().to_string(),
    productos: contar("catalogo_autocompletado")?,
    codigos: contar("codigos_barras_registrados")?,
  })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  let conn = abrir_base().unwrap_or_else(|e| panic!("{e}"));
  tauri::Builder::default()
    .manage(Base(Mutex::new(conn)))
    .invoke_handler(tauri::generate_handler![buscar_productos, buscar_codigo, info_base, fechas_con_ventas, ventas_del_dia])
    .setup(|app| {
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
      }
      Ok(())
    })
    .run(tauri::generate_context!())
    .expect("error while building tauri application");
}
