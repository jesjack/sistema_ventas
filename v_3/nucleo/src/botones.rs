//! Botones configurables de la caja (P1 en `repaso_decisiones_sin_calc.md`): los mismos datos que
//! la v2 (`botones`, `boton_visibilidad`), importados con el resto de la base.
//!
//! Lo configurable es qué botones hay, su etiqueta, su orden, si están activos y quién ve cada uno.
//! La ACCIÓN de cada botón (`archivo_accion`, el nombre del archivo de `v_2/acciones/`) está
//! programada en la caja: un botón cuya acción no existe en esta versión se muestra deshabilitado.

use rusqlite::params;
use serde::Serialize;

use crate::base::{Base, ErrorBase};

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Boton {
    pub id: i64,
    pub nombre_interno: String,
    pub etiqueta: String,
    /// La acción que ejecuta (`cobrar_carrito`, `abrir_caja`…).
    pub accion: String,
    pub orden: i64,
}

impl Base {
    /// Los botones activos que ve un usuario, en su orden (y por id a igual orden), como la v2.
    pub fn botones_de(&self, usuario_id: i64) -> Result<Vec<Boton>, ErrorBase> {
        let mut consulta = self.con.prepare_cached(
            "SELECT b.id, b.nombre_interno, b.etiqueta, b.archivo_accion, b.orden
             FROM botones b JOIN boton_visibilidad v ON v.boton_id = b.id
             WHERE v.usuario_id = ?1 AND b.activo = 1
             ORDER BY b.orden, b.id",
        )?;
        let filas = consulta.query_map(params![usuario_id], |f| {
            Ok(Boton { id: f.get(0)?, nombre_interno: f.get(1)?, etiqueta: f.get(2)?, accion: f.get(3)?, orden: f.get(4)? })
        })?;
        Ok(filas.collect::<Result<_, _>>()?)
    }
}

/// Un botón con todo lo que se administra: también inactivo, y quién lo ve.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct BotonAdmin {
    pub id: i64,
    pub etiqueta: String,
    pub accion: String,
    pub orden: i64,
    pub activo: bool,
    /// Los usuarios que lo ven (ids).
    pub visible_para: Vec<i64>,
}

/// Un usuario en la matriz de botones (la plantilla primero).
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct UsuarioBotones {
    pub id: i64,
    pub nombre: String,
    pub plantilla: bool,
}

impl Base {
    /// Todos los botones (activos o no), en su orden, con quién ve cada uno.
    pub fn botones_admin(&self) -> Result<Vec<BotonAdmin>, ErrorBase> {
        let mut consulta = self.con.prepare("SELECT id, etiqueta, archivo_accion, orden, activo FROM botones ORDER BY orden, id")?;
        let mut botones: Vec<BotonAdmin> = consulta
            .query_map([], |f| {
                Ok(BotonAdmin { id: f.get(0)?, etiqueta: f.get(1)?, accion: f.get(2)?, orden: f.get(3)?, activo: f.get::<_, i64>(4)? != 0, visible_para: Vec::new() })
            })?
            .collect::<Result<_, _>>()?;
        let mut vis = self.con.prepare("SELECT boton_id, usuario_id FROM boton_visibilidad ORDER BY usuario_id")?;
        for fila in vis.query_map([], |f| Ok((f.get::<_, i64>(0)?, f.get::<_, i64>(1)?)))? {
            let (boton, usuario) = fila?;
            if let Some(b) = botones.iter_mut().find(|b| b.id == boton) {
                b.visible_para.push(usuario);
            }
        }
        Ok(botones)
    }

    /// Los usuarios de la matriz: la plantilla primero; luego los demás activos, por nombre.
    pub fn usuarios_botones(&self) -> Result<Vec<UsuarioBotones>, ErrorBase> {
        let mut consulta = self.con.prepare(
            "SELECT id, nombre_usuario FROM usuarios_sistema WHERE activo = 1 OR nombre_usuario = ?1
             ORDER BY nombre_usuario <> ?1, nombre_usuario COLLATE NOCASE, id",
        )?;
        let filas = consulta.query_map(params![crate::sesiones::USUARIO_PLANTILLA], |f| {
            let nombre: String = f.get(1)?;
            Ok(UsuarioBotones { id: f.get(0)?, plantilla: nombre == crate::sesiones::USUARIO_PLANTILLA, nombre })
        })?;
        Ok(filas.collect::<Result<_, _>>()?)
    }

    pub fn poner_visible(&mut self, boton_id: i64, usuario_id: i64, visible: bool) -> Result<(), ErrorBase> {
        if visible {
            self.con.execute("INSERT OR IGNORE INTO boton_visibilidad (boton_id, usuario_id) VALUES (?1, ?2)", params![boton_id, usuario_id])?;
        } else {
            self.con.execute("DELETE FROM boton_visibilidad WHERE boton_id = ?1 AND usuario_id = ?2", params![boton_id, usuario_id])?;
        }
        Ok(())
    }

    pub fn poner_activo(&mut self, boton_id: i64, activo: bool) -> Result<(), ErrorBase> {
        self.con.execute(
            "UPDATE botones SET activo = ?1, actualizado_en = datetime('now', 'localtime') WHERE id = ?2",
            params![i64::from(activo), boton_id],
        )?;
        Ok(())
    }

    /// Reordena: los botones quedan en el orden de `ids` (0, 1, 2…). Los que no estén, al final.
    pub fn ordenar_botones(&mut self, ids: &[i64]) -> Result<(), ErrorBase> {
        let tx = self.con.transaction()?;
        for (orden, id) in ids.iter().enumerate() {
            tx.execute("UPDATE botones SET orden = ?1, actualizado_en = datetime('now', 'localtime') WHERE id = ?2", params![orden as i64, id])?;
        }
        // Los que no se nombraron quedan después (ids numéricos: se pueden escribir en la consulta).
        let lista = ids.iter().map(i64::to_string).collect::<Vec<_>>().join(",");
        tx.execute(&format!("UPDATE botones SET orden = orden + ?1 WHERE id NOT IN ({lista})"), params![ids.len() as i64])?;
        tx.commit()?;
        Ok(())
    }

    /// Cambia la etiqueta y la acción de un botón. `false` si no existe.
    pub fn editar_boton(&mut self, id: i64, etiqueta: &str, accion: &str) -> Result<bool, String> {
        let (etiqueta, accion) = (etiqueta.trim(), accion.trim());
        if etiqueta.is_empty() || accion.is_empty() {
            return Err("El botón necesita una etiqueta y una acción.".into());
        }
        let n = self
            .con
            .execute(
                "UPDATE botones SET etiqueta = ?1, archivo_accion = ?2, actualizado_en = datetime('now', 'localtime') WHERE id = ?3",
                params![etiqueta, accion, id],
            )
            .map_err(|e| e.to_string())?;
        Ok(n > 0)
    }

    /// Crea un botón al final, activo y visible para la plantilla (como sus usuarios nuevos).
    /// `nombre_interno` (único) se deriva de la acción.
    pub fn crear_boton(&mut self, etiqueta: &str, accion: &str) -> Result<i64, String> {
        let (etiqueta, accion) = (etiqueta.trim(), accion.trim());
        if etiqueta.is_empty() || accion.is_empty() {
            return Err("El botón necesita una etiqueta y una acción.".into());
        }
        let existentes: Vec<String> = self
            .con
            .prepare("SELECT lower(nombre_interno) FROM botones")
            .and_then(|mut c| c.query_map([], |f| f.get(0))?.collect())
            .map_err(|e| e.to_string())?;
        let mut nombre = accion.to_lowercase();
        let mut n = 2;
        while existentes.contains(&nombre) {
            nombre = format!("{}_{n}", accion.to_lowercase());
            n += 1;
        }
        let tx = self.con.transaction().map_err(|e| e.to_string())?;
        tx.execute(
            "INSERT INTO botones (nombre_interno, etiqueta, archivo_accion, orden, activo)
             VALUES (?1, ?2, ?3, (SELECT COALESCE(MAX(orden), -1) + 1 FROM botones), 1)",
            params![nombre, etiqueta, accion],
        )
        .map_err(|e| e.to_string())?;
        let id = tx.last_insert_rowid();
        tx.execute(
            "INSERT OR IGNORE INTO boton_visibilidad (boton_id, usuario_id)
             SELECT ?1, id FROM usuarios_sistema WHERE nombre_usuario = ?2",
            params![id, crate::sesiones::USUARIO_PLANTILLA],
        )
        .map_err(|e| e.to_string())?;
        tx.commit().map_err(|e| e.to_string())?;
        Ok(id)
    }
}

#[cfg(test)]
mod pruebas {
    use super::*;

    #[test]
    fn cada_usuario_ve_sus_botones_activos_en_orden() {
        let base = Base::en_memoria_v3().unwrap();
        base.ejecutar_sql(
            "INSERT INTO usuarios_sistema (id, nombre_usuario, sistema_operativo) VALUES (10, 'ana', 'Linux'), (11, 'beto', 'Linux');
             INSERT INTO botones (id, nombre_interno, etiqueta, archivo_accion, orden, activo) VALUES
                 (1, 'cobrar_carrito', 'COBRAR CARRITO', 'cobrar_carrito', 1, 1),
                 (2, 'ver_ventas', 'VER VENTAS', 'ver_ventas', 0, 1),
                 (3, 'abrir_caja', 'ABRIR CAJA', 'abrir_caja', 7, 1),
                 (4, 'viejo', 'VIEJO', 'ping', 2, 0);
             INSERT INTO boton_visibilidad (boton_id, usuario_id) VALUES (1, 10), (2, 10), (3, 10), (4, 10), (1, 11);",
        )
        .unwrap();
        let etiquetas = |u: i64| base.botones_de(u).unwrap().into_iter().map(|b| b.etiqueta).collect::<Vec<_>>();
        assert_eq!(etiquetas(10), ["VER VENTAS", "COBRAR CARRITO", "ABRIR CAJA"], "en orden y sin el inactivo");
        assert_eq!(etiquetas(11), ["COBRAR CARRITO"]);
        assert!(etiquetas(99).is_empty());
    }

    #[test]
    fn administrar_botones_y_plantilla_para_usuarios_nuevos() {
        use crate::DatosUsuario;
        let mut base = Base::en_memoria_v3().unwrap();
        let plantilla: i64 = base.con.query_row("SELECT id FROM usuarios_sistema WHERE nombre_usuario = '__default__'", [], |f| f.get(0)).unwrap();
        let cobrar = base.crear_boton("COBRAR CARRITO", "cobrar_carrito").unwrap();
        let abrir = base.crear_boton("ABRIR CAJA", "abrir_caja").unwrap();
        let otro_cobrar = base.crear_boton("COBRAR 2", "cobrar_carrito").unwrap();
        base.poner_visible(abrir, plantilla, false).unwrap();
        // Un usuario nuevo hereda lo que hoy tiene la plantilla.
        let datos = |n: &str| DatosUsuario { nombre_usuario: n.into(), sistema_operativo: "Linux".into(), version_sistema: "x".into(), nombre_equipo: "pc".into(), dominio: "".into() };
        let (ana, nuevo) = base.asegurar_usuario(&datos("ana")).unwrap();
        assert!(nuevo);
        let suyos: Vec<_> = base.botones_de(ana).unwrap().into_iter().map(|b| b.id).collect();
        assert_eq!(suyos, [cobrar, otro_cobrar]);
        // Desde ahí son suyos: cambiar la plantilla no la cambia a ella.
        base.poner_visible(abrir, plantilla, true).unwrap();
        assert_eq!(base.botones_de(ana).unwrap().len(), 2);
        // Orden, activo, edición.
        base.ordenar_botones(&[otro_cobrar, cobrar]).unwrap();
        base.poner_activo(cobrar, false).unwrap();
        assert!(base.editar_boton(otro_cobrar, "COBRAR", "cobrar_carrito").unwrap());
        let admin = base.botones_admin().unwrap();
        let resumen: Vec<_> = admin.iter().map(|b| (b.etiqueta.as_str(), b.activo)).collect();
        assert_eq!(resumen, [("COBRAR", true), ("COBRAR CARRITO", false), ("ABRIR CAJA", true)]);
        assert!(admin[0].visible_para.contains(&ana) && admin[0].visible_para.contains(&plantilla));
        let usuarios = base.usuarios_botones().unwrap();
        assert!(usuarios[0].plantilla, "la plantilla primero");
        assert!(base.crear_boton(" ", "x").is_err());
    }
}
