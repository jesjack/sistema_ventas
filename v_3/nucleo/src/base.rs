//! Conexión a `ventas.db` con la misma configuración que la v2 (`services/base_datos.py`).

use std::path::Path;
use std::time::Duration;

use rusqlite::Connection;

/// Cuánto espera una conexión a que otra suelte la base antes de fallar con "database is locked".
/// Igual que `ESPERA_BLOQUEO_SEGUNDOS` de la v2: varios procesos escriben en la misma base.
pub const ESPERA_BLOQUEO: Duration = Duration::from_secs(15);

/// Tablas y columnas que este núcleo usa. Si falta alguna, la base no es compatible (p. ej. es
/// de una v2 vieja que todavía no migró): se avisa en vez de escribir a medias.
pub const ESQUEMA_REQUERIDO: &[(&str, &[&str])] = &[
    ("ventas", &["id", "fecha", "hora", "total", "recibido", "cambio", "sesion_id"]),
    ("venta_items", &["id", "venta_id", "producto", "precio", "cantidad", "subtotal"]),
    ("eventos_especiales", &["id", "fecha", "hora", "evento", "detalle", "sesion_id"]),
    ("cortes_caja", &["id", "fecha", "hora", "ultima_venta_id", "ultimo_evento_id", "sesion_id"]),
    ("cortes_caja_cambio", &["id", "corte_id", "tipo", "denominacion", "cantidad"]),
    ("catalogo_autocompletado", &["id", "producto"]),
    ("codigos_barras_registrados", &["id", "codigo_barras", "producto_id", "precio_venta"]),
];

#[derive(Debug, thiserror::Error)]
pub enum ErrorBase {
    #[error("SQLite: {0}")]
    Sqlite(#[from] rusqlite::Error),
    #[error("la base no es compatible; falta: {0}")]
    Incompatible(String),
}

/// Una conexión a la base. Se abre una por hilo o se protege con un `Mutex`.
pub struct Base {
    pub(crate) con: Connection,
}

impl Base {
    /// Abre la base con la configuración de la v2: espera de 15 s si está bloqueada y claves
    /// foráneas activas. No crea ni migra el esquema.
    pub fn abrir(ruta: impl AsRef<Path>) -> Result<Self, ErrorBase> {
        Self::configurar(Connection::open(ruta)?)
    }

    /// Abre la base sin poder escribir en ella (para leer la base real sin riesgo).
    pub fn abrir_solo_lectura(ruta: impl AsRef<Path>) -> Result<Self, ErrorBase> {
        Self::configurar(Connection::open_with_flags(ruta, rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY)?)
    }

    /// Una base en memoria (pruebas): sin tablas; se crean con `ejecutar_sql`.
    pub fn en_memoria() -> Result<Self, ErrorBase> {
        Self::configurar(Connection::open_in_memory()?)
    }

    fn configurar(con: Connection) -> Result<Self, ErrorBase> {
        con.busy_timeout(ESPERA_BLOQUEO)?;
        con.pragma_update(None, "foreign_keys", true)?;
        Ok(Self { con })
    }

    /// Ejecuta un guion SQL completo (pruebas: crear el esquema de la v2).
    pub fn ejecutar_sql(&self, sql: &str) -> Result<(), ErrorBase> {
        self.con.execute_batch(sql)?;
        Ok(())
    }

    /// Comprueba que existan las tablas y columnas de `ESQUEMA_REQUERIDO`. No cambia nada.
    pub fn verificar_esquema(&self) -> Result<(), ErrorBase> {
        let mut faltan = Vec::new();
        for (tabla, columnas) in ESQUEMA_REQUERIDO {
            let mut consulta = self.con.prepare(&format!("PRAGMA table_info({tabla})"))?;
            let existentes: Vec<String> = consulta.query_map([], |f| f.get::<_, String>(1))?.collect::<Result<_, _>>()?;
            if existentes.is_empty() {
                faltan.push(format!("tabla {tabla}"));
                continue;
            }
            for columna in *columnas {
                if !existentes.iter().any(|c| c == columna) {
                    faltan.push(format!("{tabla}.{columna}"));
                }
            }
        }
        if faltan.is_empty() { Ok(()) } else { Err(ErrorBase::Incompatible(faltan.join(", "))) }
    }
}

#[cfg(test)]
mod pruebas {
    use super::*;

    #[test]
    fn una_base_vacia_no_es_compatible() {
        let base = Base::en_memoria().unwrap();
        let error = base.verificar_esquema().unwrap_err().to_string();
        assert!(error.contains("tabla ventas"), "{error}");
    }

    #[test]
    fn las_claves_foraneas_quedan_activas() {
        let base = Base::en_memoria().unwrap();
        let activas: bool = base.con.pragma_query_value(None, "foreign_keys", |f| f.get(0)).unwrap();
        assert!(activas);
    }
}
