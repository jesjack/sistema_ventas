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
}
