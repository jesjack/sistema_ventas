//! El esquema PROPIO de la v3 y sus migraciones (decidido el 2026-11-24: la v3 usa su propia base y
//! los datos de la v2 se importan con `importar::desde_v2`, ver `CONTEXTO_SESION.md`).
//!
//! La versión del esquema se guarda en la propia base (`PRAGMA user_version`). Al abrir con
//! `Base::abrir_v3`, se aplican en orden las migraciones que falten, cada una en una transacción.
//! Una migración ya publicada NO se edita: los cambios van en una nueva al final de `MIGRACIONES`.

use std::path::Path;

use rusqlite::Connection;

use crate::base::{Base, ErrorBase};

/// Las migraciones en orden: la posición + 1 es la versión que deja la base.
pub const MIGRACIONES: &[&str] = &[include_str!("esquema/v1.sql"), include_str!("esquema/v2.sql"), include_str!("esquema/v3.sql"), include_str!("esquema/v4.sql"), include_str!("esquema/v5.sql"), include_str!("esquema/v6.sql"), include_str!("esquema/v7.sql"), include_str!("esquema/v8.sql")];

/// La versión más reciente del esquema.
pub fn version_actual() -> i64 {
    MIGRACIONES.len() as i64
}

fn version(con: &Connection) -> Result<i64, ErrorBase> {
    Ok(con.pragma_query_value(None, "user_version", |f| f.get(0))?)
}

/// ¿Tiene tablas? Una base con tablas y versión 0 no es de la v3 (p. ej. es de la v2).
fn tiene_tablas(con: &Connection) -> Result<bool, ErrorBase> {
    let n: i64 = con.query_row("SELECT count(*) FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'", [], |f| f.get(0))?;
    Ok(n > 0)
}

impl Base {
    /// Abre (o crea) una base de la v3 y le aplica las migraciones que falten.
    ///
    /// Se niega a tocar una base que ya tiene tablas pero no es de la v3 (versión 0): sería la de
    /// la v2, que se IMPORTA (`importar::desde_v2`), nunca se migra en su sitio.
    pub fn abrir_v3(ruta: impl AsRef<Path>) -> Result<Self, ErrorBase> {
        let mut base = Self::abrir(ruta)?;
        base.migrar()?;
        Ok(base)
    }

    /// Una base de la v3 en memoria, ya migrada (pruebas).
    pub fn en_memoria_v3() -> Result<Self, ErrorBase> {
        let mut base = Self::en_memoria()?;
        base.migrar()?;
        Ok(base)
    }

    /// Versión del esquema de esta base.
    pub fn version_esquema(&self) -> Result<i64, ErrorBase> {
        version(&self.con)
    }

    fn migrar(&mut self) -> Result<(), ErrorBase> {
        let actual = version(&self.con)?;
        if actual == 0 && tiene_tablas(&self.con)? {
            return Err(ErrorBase::Incompatible(
                "esta base tiene tablas pero no es de la v3 (¿es la de la v2?): se importa, no se migra".into(),
            ));
        }
        if actual > version_actual() {
            return Err(ErrorBase::Incompatible(format!(
                "la base es de una versión más nueva de la caja (esquema {actual}; esta conoce hasta {})",
                version_actual()
            )));
        }
        for (indice, sql) in MIGRACIONES.iter().enumerate().skip(actual as usize) {
            let tx = self.con.transaction()?;
            tx.execute_batch(sql)?;
            tx.pragma_update(None, "user_version", indice as i64 + 1)?;
            tx.commit()?;
        }
        Ok(())
    }
}

#[cfg(test)]
mod pruebas {
    use super::*;

    #[test]
    fn una_base_nueva_queda_en_la_ultima_version_y_es_compatible() {
        let base = Base::en_memoria_v3().unwrap();
        assert_eq!(base.version_esquema().unwrap(), version_actual());
        base.verificar_esquema().unwrap();
        let plantilla: String = base.con.query_row("SELECT nombre_usuario FROM usuarios_sistema", [], |f| f.get(0)).unwrap();
        assert_eq!(plantilla, "__default__");
        let turno: i64 = base.con.query_row("SELECT numero FROM turno_caja", [], |f| f.get(0)).unwrap();
        assert_eq!(turno, 0);
    }

    #[test]
    fn migrar_dos_veces_no_cambia_nada() {
        let mut base = Base::en_memoria_v3().unwrap();
        base.migrar().unwrap();
        let usuarios: i64 = base.con.query_row("SELECT count(*) FROM usuarios_sistema", [], |f| f.get(0)).unwrap();
        assert_eq!(usuarios, 1);
    }

    #[test]
    fn se_niega_a_migrar_una_base_de_la_v2() {
        let mut base = Base::en_memoria().unwrap();
        base.ejecutar_sql(include_str!("../pruebas_v2/esquema_v2.sql")).unwrap();
        let error = base.migrar().unwrap_err().to_string();
        assert!(error.contains("se importa, no se migra"), "{error}");
    }

    #[test]
    fn de_la_version_1_se_llega_a_la_ultima() {
        // De una base en versión 1 (como quedaría una instalación vieja) se llega a la última.
        let mut base = Base::en_memoria().unwrap();
        base.ejecutar_sql(MIGRACIONES[0]).unwrap();
        base.con.pragma_update(None, "user_version", 1).unwrap();
        base.migrar().unwrap();
        assert_eq!(base.version_esquema().unwrap(), version_actual());
    }
}
