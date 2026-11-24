//! Ventas, eventos especiales y cortes de caja (`v_2/services/ventas_service.py`).
//!
//! Las mismas tablas, columnas y valores que escribe la v2. Cada operación va en una transacción.

use chrono::Local;
use rusqlite::{OptionalExtension, params};
use serde::Serialize;

use crate::base::{Base, ErrorBase};
use crate::carrito::FilaCarrito;
use crate::corte::{EVENTO_CORTE, PiezaCambio, producto_de_cambio, resumen_del_cambio};

/// Fecha (`AAAA-MM-DD`) y hora (`HH:MM:SS`) locales, como las guarda la v2.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Momento {
    pub fecha: String,
    pub hora: String,
}

impl Momento {
    pub fn ahora() -> Self {
        let ahora = Local::now();
        Self { fecha: ahora.format("%Y-%m-%d").to_string(), hora: ahora.format("%H:%M:%S").to_string() }
    }

    pub fn nuevo(fecha: &str, hora: &str) -> Self {
        Self { fecha: fecha.to_string(), hora: hora.to_string() }
    }
}

/// Una fila de VENTAS REALIZADAS: un producto vendido, un evento (sin precio, cantidad ni
/// subtotal) o, tras un corte, una pieza del cambio que se dejó en la caja.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct FilaVentas {
    pub hora: String,
    pub producto: String,
    pub precio: Option<f64>,
    pub cantidad: Option<i64>,
    pub subtotal: Option<f64>,
}

impl Base {
    /// Registra una venta con sus productos. Una venta sin productos no se registra (`None`),
    /// como en la v2. Devuelve el id de la venta.
    pub fn registrar_venta(
        &mut self,
        items: &[FilaCarrito],
        recibido: f64,
        cambio: f64,
        momento: &Momento,
        sesion_id: Option<i64>,
    ) -> Result<Option<i64>, ErrorBase> {
        if items.is_empty() {
            return Ok(None);
        }
        let total: f64 = items.iter().map(|i| i.subtotal).sum();
        let tx = self.con.transaction()?;
        tx.execute(
            "INSERT INTO ventas (fecha, hora, total, recibido, cambio, sesion_id) VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
            params![momento.fecha, momento.hora, total, recibido, cambio, sesion_id],
        )?;
        let venta_id = tx.last_insert_rowid();
        {
            let mut insertar = tx.prepare(
                "INSERT INTO venta_items (venta_id, producto, precio, cantidad, subtotal) VALUES (?1, ?2, ?3, ?4, ?5)",
            )?;
            for i in items {
                insertar.execute(params![venta_id, i.producto, i.precio, i.cantidad, i.subtotal])?;
            }
        }
        tx.commit()?;
        Ok(Some(venta_id))
    }

    /// Registra un evento del historial ("APERTURA DE CAJA"…). Devuelve su id.
    pub fn registrar_evento(
        &mut self,
        evento: &str,
        detalle: Option<&str>,
        momento: &Momento,
        sesion_id: Option<i64>,
    ) -> Result<i64, ErrorBase> {
        self.con.execute(
            "INSERT INTO eventos_especiales (fecha, hora, evento, detalle, sesion_id) VALUES (?1, ?2, ?3, ?4, ?5)",
            params![momento.fecha, momento.hora, evento, detalle, sesion_id],
        )?;
        Ok(self.con.last_insert_rowid())
    }

    /// Corte de caja: deja un evento "CORTE DE CAJA" con el resumen del cambio, y desde aquí la
    /// tabla del día empieza con `cambio` (lo que se dejó en la caja). Las piezas con cantidad 0
    /// no se guardan. Devuelve el id del corte.
    pub fn registrar_corte(&mut self, cambio: &[PiezaCambio], momento: &Momento, sesion_id: Option<i64>) -> Result<i64, ErrorBase> {
        let tx = self.con.transaction()?;
        tx.execute(
            "INSERT INTO eventos_especiales (fecha, hora, evento, detalle, sesion_id) VALUES (?1, ?2, ?3, ?4, ?5)",
            params![momento.fecha, momento.hora, EVENTO_CORTE, format!("Cambio en caja: {}", resumen_del_cambio(cambio)), sesion_id],
        )?;
        // Todo lo que ya existe (incluido el evento de arriba) queda antes del corte.
        tx.execute(
            "INSERT INTO cortes_caja (fecha, hora, ultima_venta_id, ultimo_evento_id, sesion_id)
             VALUES (?1, ?2, (SELECT COALESCE(MAX(id), 0) FROM ventas), (SELECT COALESCE(MAX(id), 0) FROM eventos_especiales), ?3)",
            params![momento.fecha, momento.hora, sesion_id],
        )?;
        let corte_id = tx.last_insert_rowid();
        {
            let mut insertar = tx.prepare(
                "INSERT INTO cortes_caja_cambio (corte_id, tipo, denominacion, cantidad) VALUES (?1, ?2, ?3, ?4)",
            )?;
            for p in cambio.iter().filter(|p| p.cantidad != 0) {
                insertar.execute(params![corte_id, p.tipo, p.denominacion, p.cantidad])?;
            }
        }
        tx.commit()?;
        Ok(corte_id)
    }

    /// Las filas de VENTAS REALIZADAS de un día, en orden: por hora; a la misma hora, las ventas
    /// antes que los eventos; y en orden de registro.
    ///
    /// Con `desde_ultimo_corte` (la vista de la caja), si ese día hubo un corte las filas empiezan
    /// con el cambio que se dejó en la caja, una por denominación, seguido solo de lo posterior.
    /// Sin él (revisar un día), sale el día completo, con el corte como un evento más.
    pub fn ventas_del_dia(&self, fecha: &str, desde_ultimo_corte: bool) -> Result<Vec<FilaVentas>, ErrorBase> {
        let mut filas = Vec::new();
        let (mut ultima_venta, mut ultimo_evento) = (0_i64, 0_i64);
        if desde_ultimo_corte {
            let corte: Option<(i64, String, i64, i64)> = self
                .con
                .query_row(
                    "SELECT id, hora, ultima_venta_id, ultimo_evento_id FROM cortes_caja WHERE fecha = ?1 ORDER BY id DESC LIMIT 1",
                    params![fecha],
                    |f| Ok((f.get(0)?, f.get(1)?, f.get(2)?, f.get(3)?)),
                )
                .optional()?;
            if let Some((corte_id, hora, venta, evento)) = corte {
                (ultima_venta, ultimo_evento) = (venta, evento);
                let mut consulta =
                    self.con.prepare("SELECT tipo, denominacion, cantidad FROM cortes_caja_cambio WHERE corte_id = ?1 ORDER BY id")?;
                let piezas = consulta.query_map(params![corte_id], |f| {
                    Ok(PiezaCambio { tipo: f.get(0)?, denominacion: f.get(1)?, cantidad: f.get(2)? })
                })?;
                for p in piezas {
                    let p = p?;
                    filas.push(FilaVentas {
                        hora: hora.clone(),
                        producto: producto_de_cambio(&p.tipo),
                        precio: Some(p.denominacion),
                        cantidad: Some(p.cantidad),
                        subtotal: Some(p.denominacion * p.cantidad as f64),
                    });
                }
            }
        }
        let mut consulta = self.con.prepare(
            "SELECT hora, producto, precio, cantidad, subtotal FROM (
                 SELECT v.hora AS hora, i.producto AS producto, i.precio AS precio, i.cantidad AS cantidad,
                        i.subtotal AS subtotal, v.id AS orden_principal, i.id AS orden_secundario, 0 AS tipo_registro
                 FROM ventas v JOIN venta_items i ON i.venta_id = v.id
                 WHERE v.fecha = ?1 AND v.id > ?2
                 UNION ALL
                 SELECT e.hora, e.evento, NULL, NULL, NULL, e.id, 0, 1
                 FROM eventos_especiales e
                 WHERE e.fecha = ?1 AND e.id > ?3
             )
             ORDER BY hora ASC, tipo_registro ASC, orden_principal ASC, orden_secundario ASC",
        )?;
        let resto = consulta.query_map(params![fecha, ultima_venta, ultimo_evento], |f| {
            Ok(FilaVentas { hora: f.get(0)?, producto: f.get(1)?, precio: f.get(2)?, cantidad: f.get(3)?, subtotal: f.get(4)? })
        })?;
        for fila in resto {
            filas.push(fila?);
        }
        Ok(filas)
    }

    /// Los últimos `limite` días con ventas, del más reciente al más viejo.
    pub fn dias_con_ventas(&self, limite: u32) -> Result<Vec<String>, ErrorBase> {
        let mut consulta = self.con.prepare("SELECT DISTINCT fecha FROM ventas ORDER BY fecha DESC LIMIT ?1")?;
        let dias = consulta.query_map(params![limite], |f| f.get(0))?.collect::<Result<_, _>>()?;
        Ok(dias)
    }
}
