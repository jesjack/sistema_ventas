//! Usuarios del sistema y sesiones de la caja (`v_2/services/usuarios_service.py`,
//! `v_2/services/identidad.py` y `v_2/services/seguimiento_sesion.py`).
//!
//! Cada ejecución de la caja abre una sesión ligada al usuario del sistema operativo, la mantiene
//! con un "latido" periódico (cada 60 s en la v2) y la cierra al salir. Lo que se registra durante
//! la sesión (ventas, eventos) lleva su `sesion_id`: así se sabe quién y en qué equipo.
//!
//! Un usuario se identifica por nombre + sistema operativo + equipo + dominio (la clave única de
//! `usuarios_sistema`), igual que en la v2, para que la v3 reconozca a los usuarios que ya
//! registró la v2.

use chrono::Local;
use rusqlite::{OptionalExtension, params};
use serde::Serialize;

use crate::base::{Base, ErrorBase};
use crate::ventas::Momento;

/// Usuario plantilla de la v2: nunca inicia sesión; sus botones se copian a los usuarios nuevos.
pub const USUARIO_PLANTILLA: &str = "__default__";

/// Quién usa la caja y en qué equipo.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct DatosUsuario {
    pub nombre_usuario: String,
    pub sistema_operativo: String,
    pub version_sistema: String,
    pub nombre_equipo: String,
    pub dominio: String,
}

impl DatosUsuario {
    /// Los datos del usuario y del equipo actuales, como `obtener_datos_usuario_sistema` de la v2:
    /// - usuario: `LOGNAME`, `USER`, `LNAME` o `USERNAME` (el orden de `getpass.getuser()`), en
    ///   minúsculas. La v3 no corre con `sudo`, así que no hace falta mirar `SUDO_USER`.
    /// - sistema y versión: los de `platform.system()` y `platform.version()` (uname).
    /// - equipo: el nombre del equipo; dominio: `USERDOMAIN`, `DOMAIN` o `COMPUTERDOMAIN`.
    pub fn del_sistema() -> Self {
        let variable = |nombres: &[&str]| nombres.iter().find_map(|n| std::env::var(n).ok().filter(|v| !v.trim().is_empty()));
        let leer = |ruta: &str| std::fs::read_to_string(ruta).map(|s| s.trim().to_string()).unwrap_or_default();
        Self {
            nombre_usuario: variable(&["LOGNAME", "USER", "LNAME", "USERNAME"])
                .map(|u| u.trim().to_lowercase())
                .unwrap_or_else(|| "desconocido".into()),
            sistema_operativo: match leer("/proc/sys/kernel/ostype") {
                s if s.is_empty() => std::env::consts::OS.to_string(),
                s => s,
            },
            // Tal cual, sin recortar espacios: la de la v2 (uname) termina en espacio.
            version_sistema: std::fs::read_to_string("/proc/sys/kernel/version")
                .map(|s| s.trim_end_matches('\n').to_string())
                .unwrap_or_default(),
            nombre_equipo: leer("/proc/sys/kernel/hostname"),
            dominio: variable(&["USERDOMAIN", "DOMAIN", "COMPUTERDOMAIN"]).unwrap_or_default(),
        }
    }
}

fn instante(momento: &Momento) -> String {
    format!("{} {}", momento.fecha, momento.hora)
}

impl Base {
    /// El id del usuario (y si es nuevo). Si ya existía, actualiza su versión del sistema, su
    /// último acceso y lo marca activo.
    pub fn asegurar_usuario(&mut self, datos: &DatosUsuario) -> Result<(i64, bool), ErrorBase> {
        let ahora = Local::now().format("%Y-%m-%d %H:%M:%S").to_string();
        let tx = self.con.transaction()?;
        let existente: Option<i64> = tx
            .query_row(
                "SELECT id FROM usuarios_sistema WHERE nombre_usuario = ?1 AND sistema_operativo = ?2
                 AND COALESCE(nombre_equipo, '') = ?3 AND COALESCE(dominio, '') = ?4",
                params![datos.nombre_usuario, datos.sistema_operativo, datos.nombre_equipo, datos.dominio],
                |f| f.get(0),
            )
            .optional()?;
        let resultado = match existente {
            Some(id) => {
                tx.execute(
                    "UPDATE usuarios_sistema SET version_sistema = ?1, ultimo_acceso = ?2, activo = 1 WHERE id = ?3",
                    params![datos.version_sistema, ahora, id],
                )?;
                (id, false)
            }
            None => {
                tx.execute(
                    "INSERT INTO usuarios_sistema (nombre_usuario, sistema_operativo, version_sistema, nombre_equipo, dominio, ultimo_acceso)
                     VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
                    params![datos.nombre_usuario, datos.sistema_operativo, datos.version_sistema, datos.nombre_equipo, datos.dominio, ahora],
                )?;
                (tx.last_insert_rowid(), true)
            }
        };
        tx.commit()?;
        Ok(resultado)
    }

    /// Abre una sesión del usuario. Devuelve su id.
    pub fn iniciar_sesion(&mut self, usuario_id: i64, momento: &Momento, pid: Option<i64>, detalle: Option<&str>) -> Result<i64, ErrorBase> {
        let instante = instante(momento);
        let tx = self.con.transaction()?;
        tx.execute(
            "INSERT INTO sesiones_sistema (usuario_id, inicio, ultimo_latido, salida_real, cerrada_correctamente, pid, detalle)
             VALUES (?1, ?2, ?2, NULL, 0, ?3, ?4)",
            params![usuario_id, instante, pid, detalle],
        )?;
        let sesion_id = tx.last_insert_rowid();
        tx.execute("UPDATE usuarios_sistema SET ultimo_acceso = ?1 WHERE id = ?2", params![instante, usuario_id])?;
        tx.commit()?;
        Ok(sesion_id)
    }

    /// El latido: la sesión sigue viva. Actualiza también el último acceso del usuario.
    pub fn latido(&mut self, sesion_id: i64, momento: &Momento) -> Result<(), ErrorBase> {
        let instante = instante(momento);
        let tx = self.con.transaction()?;
        tx.execute("UPDATE sesiones_sistema SET ultimo_latido = ?1 WHERE id = ?2", params![instante, sesion_id])?;
        tx.execute(
            "UPDATE usuarios_sistema SET ultimo_acceso = ?1 WHERE id = (SELECT usuario_id FROM sesiones_sistema WHERE id = ?2)",
            params![instante, sesion_id],
        )?;
        tx.commit()?;
        Ok(())
    }

    /// Cierra la sesión. `exitosa` solo cuando se SABE que fue un cierre normal; `detalle` (el
    /// motivo) reemplaza al de la apertura solo si se da.
    pub fn cerrar_sesion(&mut self, sesion_id: i64, momento: &Momento, detalle: Option<&str>, exitosa: bool) -> Result<(), ErrorBase> {
        let instante = instante(momento);
        let tx = self.con.transaction()?;
        tx.execute(
            "UPDATE sesiones_sistema SET ultimo_latido = ?1, salida_real = ?1, cerrada_correctamente = ?2,
                 detalle = COALESCE(?3, detalle) WHERE id = ?4",
            params![instante, exitosa as i64, detalle, sesion_id],
        )?;
        tx.execute(
            "UPDATE usuarios_sistema SET ultimo_acceso = ?1 WHERE id = (SELECT usuario_id FROM sesiones_sistema WHERE id = ?2)",
            params![instante, sesion_id],
        )?;
        tx.commit()?;
        Ok(())
    }
}

#[cfg(test)]
mod pruebas {
    use super::*;

    #[test]
    fn los_datos_del_sistema_tienen_usuario_y_equipo() {
        let datos = DatosUsuario::del_sistema();
        assert!(!datos.nombre_usuario.is_empty());
        assert_eq!(datos.nombre_usuario, datos.nombre_usuario.to_lowercase());
        assert!(!datos.sistema_operativo.is_empty());
    }
}

/// Compara con lo que lee la v2 en este equipo. Solo a petición:
/// `IDENTIDAD_V2=<json de obtener_datos_usuario_sistema> cargo test -- --ignored identidad`.
#[cfg(test)]
#[test]
#[ignore]
fn identidad_igual_que_la_v2() {
    let v2: std::collections::HashMap<String, String> =
        serde_json::from_str(&std::env::var("IDENTIDAD_V2").expect("IDENTIDAD_V2")).unwrap();
    let v3 = DatosUsuario::del_sistema();
    assert_eq!(v3.nombre_usuario, v2["nombre_usuario"]);
    assert_eq!(v3.sistema_operativo, v2["sistema_operativo"]);
    assert_eq!(v3.version_sistema, v2["version_sistema"]);
    assert_eq!(v3.nombre_equipo, v2["nombre_equipo"]);
    assert_eq!(v3.dominio, v2["dominio"]);
}
