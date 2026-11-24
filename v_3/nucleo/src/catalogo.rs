//! Catálogo de productos y códigos de barras (`v_2/services/catalogo_service.py`,
//! `v_2/services/codigos_barras_service.py` y `filtrar_productos` de `v_2/dialogs/varios_codigos.py`).
//!
//! - Los productos se guardan en minúsculas y sin espacios en los extremos; el nombre es único sin
//!   distinguir mayúsculas (la columna es `COLLATE NOCASE`).
//! - Se muestran con `formatear_nombre` ("mayon de faja" → "Mayon de Faja").
//! - La búsqueda de la caja es la del selector de la v2: el nombre **contiene** lo escrito o
//!   **empieza con esas iniciales** ("bb" → "blusa básica"), sin mayúsculas ni acentos. Las
//!   iniciales se saltan "de", "la", "y"… ("Blusa Básica de Licra" son "bbl").

use chrono::Local;
use rusqlite::{ErrorCode, OptionalExtension, params};
use serde::Serialize;
use unicode_normalization::{UnicodeNormalization, char::is_combining_mark};

use crate::base::{Base, ErrorBase};

/// Palabras que no cuentan para las iniciales ni se capitalizan.
pub const PREPOSICIONES: &[&str] = &["de", "del", "la", "el", "los", "las", "un", "una", "unos", "unas", "y", "o"];

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Producto {
    pub id: i64,
    pub nombre: String,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct CodigoBarras {
    pub id: i64,
    pub codigo: String,
    pub producto_id: i64,
    pub producto: String,
    pub precio: f64,
}

#[derive(Debug, thiserror::Error)]
pub enum ErrorCatalogo {
    #[error("El producto no puede estar vacío.")]
    ProductoVacio,
    #[error("Ya hay un producto con ese nombre en el catálogo.")]
    ProductoDuplicado,
    #[error("El código de barras no puede estar vacío.")]
    CodigoVacio,
    #[error("Ese código de barras ya está registrado.")]
    CodigoDuplicado,
    #[error(transparent)]
    Base(#[from] ErrorBase),
}

impl From<rusqlite::Error> for ErrorCatalogo {
    fn from(e: rusqlite::Error) -> Self {
        Self::Base(ErrorBase::from(e))
    }
}

fn es_unico_violado(e: &rusqlite::Error) -> bool {
    matches!(e, rusqlite::Error::SqliteFailure(f, _) if f.code == ErrorCode::ConstraintViolation)
}

/// Minúsculas y sin acentos (NFD sin marcas combinantes), como `_sin_acentos` de la v2.
pub fn sin_acentos(texto: &str) -> String {
    texto.to_lowercase().nfd().filter(|c| !is_combining_mark(*c)).collect()
}

/// Las iniciales de un nombre, sin las preposiciones: "Blusa Básica de Licra" → "bbl".
pub fn iniciales(nombre: &str) -> String {
    sin_acentos(nombre)
        .split_whitespace()
        .filter(|p| !PREPOSICIONES.contains(p))
        .filter_map(|p| p.chars().next())
        .collect()
}

/// "mayon de faja" → "Mayon de Faja": capitaliza cada palabra menos las preposiciones.
pub fn formatear_nombre(texto: &str) -> String {
    texto
        .split_whitespace()
        .map(|palabra| {
            let minusculas = palabra.to_lowercase();
            if PREPOSICIONES.contains(&minusculas.as_str()) {
                minusculas
            } else {
                let mut letras = palabra.chars();
                match letras.next() {
                    Some(primera) => primera.to_uppercase().chain(letras.flat_map(char::to_lowercase)).collect(),
                    None => String::new(),
                }
            }
        })
        .collect::<Vec<_>>()
        .join(" ")
}

/// ¿El producto coincide con lo escrito? Contiene el texto o empieza con esas iniciales.
/// Texto vacío: todos.
pub fn coincide(nombre: &str, texto: &str) -> bool {
    let buscado = sin_acentos(texto.trim());
    if buscado.is_empty() {
        return true;
    }
    let sin_espacios: String = buscado.chars().filter(|c| *c != ' ').collect();
    sin_acentos(nombre).contains(&buscado) || iniciales(nombre).starts_with(&sin_espacios)
}

fn ahora_local() -> String {
    Local::now().format("%Y-%m-%d %H:%M:%S").to_string()
}

const SELECT_CODIGOS: &str = "SELECT b.id, b.codigo_barras, c.id, c.producto, b.precio_venta
     FROM codigos_barras_registrados b JOIN catalogo_autocompletado c ON c.id = b.producto_id";

impl Base {
    /// Todo el catálogo, en orden alfabético sin distinguir mayúsculas.
    pub fn productos(&self) -> Result<Vec<Producto>, ErrorBase> {
        let mut consulta = self.con.prepare_cached("SELECT id, producto FROM catalogo_autocompletado ORDER BY producto COLLATE NOCASE ASC")?;
        let filas = consulta.query_map([], |f| Ok(Producto { id: f.get(0)?, nombre: f.get(1)? }))?;
        Ok(filas.collect::<Result<_, _>>()?)
    }

    /// Los productos que coinciden con lo escrito (ver `coincide`), en orden alfabético, hasta
    /// `limite`.
    pub fn buscar_productos(&self, texto: &str, limite: usize) -> Result<Vec<Producto>, ErrorBase> {
        Ok(self.productos()?.into_iter().filter(|p| coincide(&p.nombre, texto)).take(limite).collect())
    }

    /// Agrega un producto (en minúsculas, sin espacios en los extremos). Devuelve su id.
    pub fn agregar_producto(&mut self, nombre: &str, sesion_id: Option<i64>) -> Result<i64, ErrorCatalogo> {
        let nombre = nombre.trim().to_lowercase();
        if nombre.is_empty() {
            return Err(ErrorCatalogo::ProductoVacio);
        }
        match self.con.execute(
            "INSERT INTO catalogo_autocompletado (producto, creado_en, sesion_id) VALUES (?1, ?2, ?3)",
            params![nombre, ahora_local(), sesion_id],
        ) {
            Ok(_) => Ok(self.con.last_insert_rowid()),
            Err(e) if es_unico_violado(&e) => Err(ErrorCatalogo::ProductoDuplicado),
            Err(e) => Err(e.into()),
        }
    }

    /// Cambia el nombre de un producto. `false` si no existe.
    pub fn editar_producto(&mut self, id: i64, nombre: &str, sesion_id: Option<i64>) -> Result<bool, ErrorCatalogo> {
        let nombre = nombre.trim().to_lowercase();
        if nombre.is_empty() {
            return Err(ErrorCatalogo::ProductoVacio);
        }
        match self.con.execute(
            "UPDATE catalogo_autocompletado SET producto = ?1, actualizado_en = ?2, actualizado_sesion_id = ?3 WHERE id = ?4",
            params![nombre, ahora_local(), sesion_id, id],
        ) {
            Ok(cambios) => Ok(cambios > 0),
            Err(e) if es_unico_violado(&e) => Err(ErrorCatalogo::ProductoDuplicado),
            Err(e) => Err(e.into()),
        }
    }

    /// El producto y precio de un código registrado (sin distinguir mayúsculas), o `None`.
    pub fn buscar_codigo(&self, codigo: &str) -> Result<Option<CodigoBarras>, ErrorBase> {
        let codigo = codigo.trim();
        if codigo.is_empty() {
            return Ok(None);
        }
        let mut consulta = self.con.prepare_cached(&format!("{SELECT_CODIGOS} WHERE b.codigo_barras = ?1"))?;
        Ok(consulta.query_row(params![codigo], fila_codigo).optional()?)
    }

    /// Todos los códigos, por producto y código; `filtro` se busca (sin mayúsculas ni acentos) en
    /// el código y en el nombre del producto.
    pub fn codigos(&self, filtro: &str) -> Result<Vec<CodigoBarras>, ErrorBase> {
        let mut consulta = self.con.prepare_cached(&format!(
            "{SELECT_CODIGOS} ORDER BY c.producto COLLATE NOCASE ASC, b.codigo_barras COLLATE NOCASE ASC"
        ))?;
        let todos: Vec<CodigoBarras> = consulta.query_map([], fila_codigo)?.collect::<Result<_, _>>()?;
        let buscado = sin_acentos(filtro.trim());
        Ok(todos
            .into_iter()
            .filter(|c| buscado.is_empty() || sin_acentos(&c.codigo).contains(&buscado) || sin_acentos(&c.producto).contains(&buscado))
            .collect())
    }

    /// Registra un código con su producto y precio. Devuelve su id.
    pub fn registrar_codigo(&mut self, codigo: &str, producto_id: i64, precio: f64, sesion_id: Option<i64>) -> Result<i64, ErrorCatalogo> {
        let codigo = codigo.trim();
        if codigo.is_empty() {
            return Err(ErrorCatalogo::CodigoVacio);
        }
        match self.con.execute(
            "INSERT INTO codigos_barras_registrados (codigo_barras, producto_id, precio_venta, creado_en, sesion_id) VALUES (?1, ?2, ?3, ?4, ?5)",
            params![codigo, producto_id, precio, ahora_local(), sesion_id],
        ) {
            Ok(_) => Ok(self.con.last_insert_rowid()),
            Err(e) if es_unico_violado(&e) => Err(ErrorCatalogo::CodigoDuplicado),
            Err(e) => Err(e.into()),
        }
    }

    /// Cambia el texto, el producto o el precio de un código. `false` si no existe.
    pub fn actualizar_codigo(
        &mut self,
        id: i64,
        codigo: &str,
        producto_id: i64,
        precio: f64,
        sesion_id: Option<i64>,
    ) -> Result<bool, ErrorCatalogo> {
        let codigo = codigo.trim();
        if codigo.is_empty() {
            return Err(ErrorCatalogo::CodigoVacio);
        }
        match self.con.execute(
            "UPDATE codigos_barras_registrados SET codigo_barras = ?1, producto_id = ?2, precio_venta = ?3,
                 actualizado_en = ?4, actualizado_sesion_id = ?5 WHERE id = ?6",
            params![codigo, producto_id, precio, ahora_local(), sesion_id, id],
        ) {
            Ok(cambios) => Ok(cambios > 0),
            Err(e) if es_unico_violado(&e) => Err(ErrorCatalogo::CodigoDuplicado),
            Err(e) => Err(e.into()),
        }
    }
}

fn fila_codigo(f: &rusqlite::Row<'_>) -> rusqlite::Result<CodigoBarras> {
    Ok(CodigoBarras { id: f.get(0)?, codigo: f.get(1)?, producto_id: f.get(2)?, producto: f.get(3)?, precio: f.get(4)? })
}
