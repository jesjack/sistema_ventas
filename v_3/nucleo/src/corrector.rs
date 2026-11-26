//! Corrector ortográfico del catálogo (pedido el 2026-09-18 en `CLAUDE.md`): los nombres se
//! escriben a mano y llevan errores ("blusa basica", "mayon deportivo", "bycker").
//!
//! SUGIERE, nunca cambia solo. Por palabra, en este orden:
//! 1. Una corrección recordada (`correcciones_catalogo`, esquema 7): se aprende cuando alguien
//!    corrige una palabra a mano en el editor ("bycker" → "biker").
//! 2. Un diccionario de palabras de la tienda que llevan acento o ñ ("basica" → "básica").
//! 3. El propio catálogo: si la misma palabra ya se escribe con acento en otros productos al menos
//!    igual de seguido ("pantalon" → "pantalón").
//!
//! No sugiere por parecido a secas: en el catálogo real casi todos los pares a una letra son
//! femenino/masculino o singular/plural ("deportiva"/"deportivo"), que son correctos.

use std::collections::HashMap;

use rusqlite::{OptionalExtension, params};
use serde::Serialize;

use crate::base::{Base, ErrorBase};
use crate::catalogo::{Producto, sin_acentos};

/// Palabras frecuentes en una tienda de ropa que llevan acento o ñ (en minúsculas).
pub const CON_ACENTO: &[&str] = &[
    "básica", "básicas", "básico", "básicos", "térmica", "térmicas", "térmico", "térmicos", "económica", "económicas",
    "económico", "económicos", "clásica", "clásicas", "clásico", "clásicos", "elástica", "elásticas", "elástico",
    "elásticos", "plástica", "plástico", "única", "único", "pantalón", "mayón", "mallón", "camisón", "calzón", "cinturón",
    "algodón", "botón", "sostén", "suéter", "bóxer", "súper", "lencería", "bebé", "bebés", "niña", "niñas", "niño",
    "niños", "pequeña", "pequeño", "señora", "señoras", "señor", "caballero", "año", "años", "diseño", "tamaño",
    "maternidad", "lycra", "satín", "jardín", "corazón", "edición", "colección", "estampación", "compresión",
    "reducción", "invisible", "fútbol", "tenis", "pijama", "batón", "bermúda", "cálida", "cálido", "térmico",
];

/// Una sugerencia para un producto del catálogo.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Sugerencia {
    pub producto_id: i64,
    pub producto: String,
    pub sugerencia: String,
    /// Si la forma corregida ya es otro producto: habría que UNIRLOS, no renombrar.
    pub ya_existe_id: Option<i64>,
}

/// Una corrección recordada.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Correccion {
    pub incorrecta: String,
    pub correcta: String,
}

/// Lo que el corrector sabe: correcciones recordadas, diccionario y vocabulario del catálogo.
pub struct Corrector {
    correcciones: HashMap<String, String>,
    diccionario: HashMap<String, &'static str>,
    /// Por palabra sin acentos: la forma con acento más usada en el catálogo y cuántas veces.
    catalogo: HashMap<String, Vec<(String, usize)>>,
}

impl Corrector {
    pub fn nuevo(productos: &[Producto], correcciones: &[Correccion]) -> Self {
        let mut catalogo: HashMap<String, HashMap<String, usize>> = HashMap::new();
        for p in productos {
            for palabra in p.nombre.to_lowercase().split_whitespace() {
                *catalogo.entry(sin_acentos(palabra)).or_default().entry(palabra.to_string()).or_default() += 1;
            }
        }
        Self {
            correcciones: correcciones.iter().map(|c| (sin_acentos(&c.incorrecta), c.correcta.clone())).collect(),
            diccionario: CON_ACENTO.iter().map(|p| (sin_acentos(p), *p)).collect(),
            catalogo: catalogo.into_iter().map(|(k, v)| (k, v.into_iter().collect())).collect(),
        }
    }

    /// La palabra corregida, si hay algo que sugerir.
    fn palabra(&self, palabra: &str) -> Option<String> {
        let clave = sin_acentos(palabra);
        if let Some(c) = self.correcciones.get(&clave) {
            return (c != palabra).then(|| c.clone());
        }
        if let Some(d) = self.diccionario.get(&clave) {
            return (*d != palabra).then(|| d.to_string());
        }
        // Del catálogo: la forma con acento más usada, si se usa al menos igual que la escrita.
        let formas = self.catalogo.get(&clave)?;
        let usos = |f: &str| formas.iter().find(|(p, _)| p == f).map_or(0, |(_, n)| *n);
        let (mejor, n) = formas.iter().filter(|(p, _)| *p != clave).max_by_key(|(_, n)| *n)?;
        (mejor != palabra && *n >= usos(palabra)).then(|| mejor.clone())
    }

    /// El nombre corregido (en minúsculas), o `None` si no hay nada que sugerir.
    pub fn sugerir(&self, nombre: &str) -> Option<String> {
        let palabras: Vec<String> = nombre.to_lowercase().split_whitespace().map(String::from).collect();
        let mut cambio = false;
        let corregido: Vec<String> = palabras
            .iter()
            .map(|p| match self.palabra(p) {
                Some(c) => {
                    cambio = true;
                    c
                }
                None => p.clone(),
            })
            .collect();
        cambio.then(|| corregido.join(" "))
    }
}

/// ¿Dos palabras difieren solo en la terminación de género o número (deportiva/deportivo,
/// blusa/blusas)? Esos cambios son correctos y no se aprenden como correcciones.
fn solo_genero_o_numero(a: &str, b: &str) -> bool {
    let (a, b) = (sin_acentos(a), sin_acentos(b));
    let raiz = |p: &str| p.trim_end_matches('s').trim_end_matches(['a', 'o', 'e']).to_string();
    raiz(&a) == raiz(&b)
}

/// Distancia de edición (Damerau-Levenshtein restringida) entre dos palabras.
fn distancia(a: &str, b: &str) -> usize {
    let (a, b): (Vec<char>, Vec<char>) = (a.chars().collect(), b.chars().collect());
    let mut d = vec![vec![0usize; b.len() + 1]; a.len() + 1];
    for (i, fila) in d.iter_mut().enumerate() {
        fila[0] = i;
    }
    for j in 0..=b.len() {
        d[0][j] = j;
    }
    for i in 1..=a.len() {
        for j in 1..=b.len() {
            let costo = usize::from(a[i - 1] != b[j - 1]);
            d[i][j] = (d[i - 1][j] + 1).min(d[i][j - 1] + 1).min(d[i - 1][j - 1] + costo);
            if i > 1 && j > 1 && a[i - 1] == b[j - 2] && a[i - 2] == b[j - 1] {
                d[i][j] = d[i][j].min(d[i - 2][j - 2] + costo);
            }
        }
    }
    d[a.len()][b.len()]
}

/// Las correcciones que enseña un cambio de nombre hecho a mano: palabra por palabra (si tienen el
/// mismo número de palabras), las que cambiaron poco (hasta 2 letras sin contar acentos) y no solo
/// en género o número. "bycker negro" → "biker negro" enseña bycker → biker.
pub fn correcciones_de(antes: &str, despues: &str) -> Vec<Correccion> {
    let (a, b): (Vec<String>, Vec<String>) = (
        antes.to_lowercase().split_whitespace().map(String::from).collect(),
        despues.to_lowercase().split_whitespace().map(String::from).collect(),
    );
    if a.len() != b.len() {
        return Vec::new();
    }
    a.into_iter()
        .zip(b)
        .filter(|(x, y)| x != y && distancia(&sin_acentos(x), &sin_acentos(y)) <= 2 && !solo_genero_o_numero(x, y))
        .map(|(incorrecta, correcta)| Correccion { incorrecta, correcta })
        .collect()
}

impl Base {
    pub fn correcciones(&self) -> Result<Vec<Correccion>, ErrorBase> {
        let mut consulta = self.con.prepare("SELECT incorrecta, correcta FROM correcciones_catalogo ORDER BY incorrecta")?;
        let filas = consulta.query_map([], |f| Ok(Correccion { incorrecta: f.get(0)?, correcta: f.get(1)? }))?;
        Ok(filas.collect::<Result<_, _>>()?)
    }

    pub fn corrector(&self) -> Result<Corrector, ErrorBase> {
        Ok(Corrector::nuevo(&self.productos()?, &self.correcciones()?))
    }

    /// Recuerda correcciones (la incorrecta se guarda sin acentos: así sirve con o sin ellos).
    pub fn recordar_correcciones(&mut self, correcciones: &[Correccion], sesion_id: Option<i64>) -> Result<(), ErrorBase> {
        for c in correcciones {
            self.con.execute(
                "INSERT INTO correcciones_catalogo (incorrecta, correcta, creado_en, sesion_id)
                 VALUES (?1, ?2, datetime('now', 'localtime'), ?3)
                 ON CONFLICT (incorrecta) DO UPDATE SET correcta = excluded.correcta, creado_en = excluded.creado_en, sesion_id = excluded.sesion_id",
                params![sin_acentos(&c.incorrecta), c.correcta.to_lowercase(), sesion_id],
            )?;
        }
        Ok(())
    }

    pub fn olvidar_correccion(&mut self, incorrecta: &str) -> Result<bool, ErrorBase> {
        Ok(self.con.execute("DELETE FROM correcciones_catalogo WHERE incorrecta = ?1", params![sin_acentos(incorrecta)])? > 0)
    }

    /// Los productos del catálogo que tienen una sugerencia.
    pub fn revisar_catalogo(&self) -> Result<Vec<Sugerencia>, ErrorBase> {
        let productos = self.productos()?;
        let corrector = Corrector::nuevo(&productos, &self.correcciones()?);
        Ok(productos
            .iter()
            .filter_map(|p| {
                let sugerencia = corrector.sugerir(&p.nombre)?;
                let ya_existe_id = productos.iter().find(|o| o.id != p.id && o.nombre.to_lowercase() == sugerencia).map(|o| o.id);
                Some(Sugerencia { producto_id: p.id, producto: p.nombre.clone(), sugerencia, ya_existe_id })
            })
            .collect())
    }

    /// Une dos productos: los códigos de barras de `origen` pasan a `destino` y `origen` se elimina
    /// (las ventas guardan el nombre como texto: no cambian). Para corregir un nombre que choca con
    /// otro producto ya existente.
    pub fn unir_productos(&mut self, origen: i64, destino: i64, sesion_id: Option<i64>) -> Result<(), ErrorBase> {
        let tx = self.con.transaction()?;
        tx.execute(
            "UPDATE codigos_barras_registrados SET producto_id = ?1, actualizado_en = datetime('now', 'localtime'),
                 actualizado_sesion_id = ?2 WHERE producto_id = ?3",
            params![destino, sesion_id, origen],
        )?;
        tx.execute("DELETE FROM catalogo_autocompletado WHERE id = ?1", params![origen])?;
        tx.commit()?;
        Ok(())
    }

    /// Cuántos códigos de barras usan un producto (no se puede eliminar si tiene).
    pub fn codigos_del_producto(&self, producto_id: i64) -> Result<i64, ErrorBase> {
        Ok(self.con.query_row("SELECT count(*) FROM codigos_barras_registrados WHERE producto_id = ?1", params![producto_id], |f| f.get(0))?)
    }

    /// Elimina un producto sin códigos. `Ok(false)` si no existe; error si tiene códigos.
    pub fn eliminar_producto(&mut self, producto_id: i64) -> Result<bool, String> {
        let n = self.codigos_del_producto(producto_id).map_err(|e| e.to_string())?;
        if n > 0 {
            return Err(format!("No se puede eliminar: tiene {n} código{} de barras registrado{}.", if n == 1 { "" } else { "s" }, if n == 1 { "" } else { "s" }));
        }
        let existe: Option<i64> =
            self.con.query_row("SELECT id FROM catalogo_autocompletado WHERE id = ?1", params![producto_id], |f| f.get(0)).optional().map_err(|e| e.to_string())?;
        if existe.is_none() {
            return Ok(false);
        }
        self.con.execute("DELETE FROM catalogo_autocompletado WHERE id = ?1", params![producto_id]).map_err(|e| e.to_string())?;
        Ok(true)
    }
}

#[cfg(test)]
mod pruebas {
    use super::*;

    fn p(id: i64, nombre: &str) -> Producto {
        Producto { id, nombre: nombre.into() }
    }

    #[test]
    fn sugiere_acentos_del_diccionario_y_del_catalogo_sin_tocar_genero() {
        let productos = [p(1, "pantalón cargo"), p(2, "pantalón largo"), p(3, "pantalon de vestir"), p(4, "blusa deportiva"), p(5, "short deportivo")];
        let c = Corrector::nuevo(&productos, &[]);
        assert_eq!(c.sugerir("blusa basica"), Some("blusa básica".into()));
        assert_eq!(c.sugerir("pantalon de vestir"), Some("pantalón de vestir".into()), "el catálogo lo escribe con acento más veces");
        assert_eq!(c.sugerir("Termica Niño"), Some("térmica niño".into()));
        assert_eq!(c.sugerir("blusa deportiva"), None, "deportiva/deportivo no es un error");
        assert_eq!(c.sugerir("pantalón cargo"), None);
    }

    #[test]
    fn aprende_correcciones_hechas_a_mano_pero_no_las_de_genero() {
        assert_eq!(correcciones_de("bycker negro", "biker negro"), [Correccion { incorrecta: "bycker".into(), correcta: "biker".into() }]);
        assert!(correcciones_de("blusa deportiva", "blusa deportivo").is_empty());
        assert!(correcciones_de("blusa", "blusas").is_empty());
        assert!(correcciones_de("short", "short rojo").is_empty(), "distinto número de palabras");
        assert!(correcciones_de("faja", "blusa").is_empty(), "demasiado distinta: es otro producto");
        let c = Corrector::nuevo(&[], &correcciones_de("bycker negro", "biker negro"));
        assert_eq!(c.sugerir("short bycker"), Some("short biker".into()));
    }

    #[test]
    fn revisar_unir_y_eliminar_en_la_base() {
        let mut base = Base::en_memoria_v3().unwrap();
        let malo = base.agregar_producto("blusa basica", None).unwrap();
        let bueno = base.agregar_producto("blusa básica", None).unwrap();
        base.agregar_producto("faja", None).unwrap();
        base.registrar_codigo("A1", malo, 150.0, None).unwrap();
        let revision = base.revisar_catalogo().unwrap();
        assert_eq!(revision.len(), 1);
        assert_eq!((revision[0].producto_id, revision[0].ya_existe_id), (malo, Some(bueno)));
        assert!(base.eliminar_producto(malo).unwrap_err().contains("1 código de barras"));
        base.unir_productos(malo, bueno, None).unwrap();
        assert_eq!(base.buscar_codigo("A1").unwrap().unwrap().producto, "blusa básica");
        assert!(base.revisar_catalogo().unwrap().is_empty());
        base.recordar_correcciones(&correcciones_de("bycker", "biker"), None).unwrap();
        assert_eq!(base.corrector().unwrap().sugerir("Bycker"), Some("biker".into()));
        assert!(base.olvidar_correccion("bycker").unwrap());
    }
}
