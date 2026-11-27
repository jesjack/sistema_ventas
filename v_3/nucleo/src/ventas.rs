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

/// El corte con el que empieza un día, quién lo hizo y su última verificación.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct CorteDelDia {
    pub id: i64,
    pub fecha: String,
    pub hora: String,
    pub total: f64,
    pub usuario: Option<String>,
    pub verificacion: Option<Verificacion>,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Verificacion {
    pub en: String,
    pub contado: f64,
    pub usuario: Option<String>,
}

/// Un corte que sigue valiendo: nadie ha vendido después de él.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct CorteListo {
    pub id: i64,
    pub fecha: String,
    pub hora: String,
    /// Lo que se dejó de cambio.
    pub total: f64,
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
    /// Un producto de una venta pagada con tarjeta (no entra a la caja). Desde el esquema 8.
    pub tarjeta: bool,
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
        self.registrar_venta_con(items, recibido, cambio, false, momento, sesion_id)
    }

    /// Cobro rápido sin ticket (D15): recibido = total, cambio = 0 y la marca `sin_ticket`. Solo en
    /// una base de la v3 (la columna llega con la versión 3 del esquema).
    pub fn registrar_venta_sin_ticket(&mut self, items: &[FilaCarrito], momento: &Momento, sesion_id: Option<i64>) -> Result<Option<i64>, ErrorBase> {
        let total: f64 = items.iter().map(|i| i.subtotal).sum();
        self.registrar_venta_con(items, total, 0.0, true, momento, sesion_id)
    }

    /// Venta pagada con tarjeta (esquema 8): recibido = total, cambio = 0, `metodo_pago = 'tarjeta'`.
    /// El dinero va a Mercado Pago, no a la caja: quien llama NO abre el cajón.
    pub fn registrar_venta_tarjeta(&mut self, items: &[FilaCarrito], momento: &Momento, sesion_id: Option<i64>) -> Result<Option<i64>, ErrorBase> {
        let total: f64 = items.iter().map(|i| i.subtotal).sum();
        let Some(id) = self.registrar_venta_con(items, total, 0.0, false, momento, sesion_id)? else { return Ok(None) };
        self.con.execute("UPDATE ventas SET metodo_pago = 'tarjeta' WHERE id = ?1", params![id])?;
        Ok(Some(id))
    }

    /// ¿La tabla tiene esa columna? (Una base de la v2 no tiene las que agregó la v3.)
    fn tiene_columna(&self, tabla: &str, columna: &str) -> Result<bool, ErrorBase> {
        let mut consulta = self.con.prepare(&format!("PRAGMA table_info({tabla})"))?;
        let columnas: Vec<String> = consulta.query_map([], |f| f.get(1))?.collect::<Result<_, _>>()?;
        Ok(columnas.iter().any(|c| c == columna))
    }

    fn registrar_venta_con(
        &mut self,
        items: &[FilaCarrito],
        recibido: f64,
        cambio: f64,
        sin_ticket: bool,
        momento: &Momento,
        sesion_id: Option<i64>,
    ) -> Result<Option<i64>, ErrorBase> {
        if items.is_empty() {
            return Ok(None);
        }
        let total: f64 = items.iter().map(|i| i.subtotal).sum();
        let tx = self.con.transaction()?;
        if sin_ticket {
            tx.execute(
                "INSERT INTO ventas (fecha, hora, total, recibido, cambio, sesion_id, sin_ticket) VALUES (?1, ?2, ?3, ?4, ?5, ?6, 1)",
                params![momento.fecha, momento.hora, total, recibido, cambio, sesion_id],
            )?;
        } else {
            // Sin nombrar `sin_ticket`: así también funciona sobre el esquema de la v2 (pruebas).
            tx.execute(
                "INSERT INTO ventas (fecha, hora, total, recibido, cambio, sesion_id) VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
                params![momento.fecha, momento.hora, total, recibido, cambio, sesion_id],
            )?;
        }
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
                        tarjeta: false,
                    });
                }
            }
        }
        // El método de pago solo existe en una base de la v3 (esquema 8); en una de la v2, todo es efectivo.
        let tarjeta = if self.tiene_columna("ventas", "metodo_pago")? { "v.metodo_pago = 'tarjeta'" } else { "0" };
        let mut consulta = self.con.prepare(&format!(
            "SELECT hora, producto, precio, cantidad, subtotal, tarjeta FROM (
                 SELECT v.hora AS hora, i.producto AS producto, i.precio AS precio, i.cantidad AS cantidad,
                        i.subtotal AS subtotal, {tarjeta} AS tarjeta, v.id AS orden_principal, i.id AS orden_secundario, 0 AS tipo_registro
                 FROM ventas v JOIN venta_items i ON i.venta_id = v.id
                 WHERE v.fecha = ?1 AND v.id > ?2
                 UNION ALL
                 SELECT e.hora, e.evento, NULL, NULL, NULL, 0, e.id, 0, 1
                 FROM eventos_especiales e
                 WHERE e.fecha = ?1 AND e.id > ?3
             )
             ORDER BY hora ASC, tipo_registro ASC, orden_principal ASC, orden_secundario ASC"
        ))?;
        let resto = consulta.query_map(params![fecha, ultima_venta, ultimo_evento], |f| {
            Ok(FilaVentas { hora: f.get(0)?, producto: f.get(1)?, precio: f.get(2)?, cantidad: f.get(3)?, subtotal: f.get(4)?, tarjeta: f.get(5)? })
        })?;
        for fila in resto {
            filas.push(fila?);
        }
        Ok(filas)
    }

    /// VENTAS REALIZADAS de hoy en la v3: como `ventas_del_dia(hoy, true)`, pero si hoy no hay corte
    /// y el último corte de un día anterior fue lo último de su día (ninguna venta después, ni ese
    /// día ni en días intermedios), su cambio pasa a ser el cambio con el que empieza hoy (pedido el
    /// 2026-11-24: Nancy hace el corte al cerrar y la empleada lo verifica al día siguiente).
    pub fn ventas_de_hoy(&self, hoy: &str) -> Result<Vec<FilaVentas>, ErrorBase> {
        let filas = self.ventas_del_dia(hoy, true)?;
        let corte_hoy: bool = self.con.query_row("SELECT EXISTS(SELECT 1 FROM cortes_caja WHERE fecha = ?1)", params![hoy], |f| f.get(0))?;
        if corte_hoy {
            return Ok(filas);
        }
        let Some(listo) = self.corte_que_pasa_a(hoy)? else { return Ok(filas) };
        let mut con_cambio = self.cambio_del_corte(listo.id, &listo.hora)?;
        con_cambio.extend(filas);
        Ok(con_cambio)
    }

    /// El último corte de un día anterior a `hoy`, si nadie vendió después de él antes de `hoy`.
    fn corte_que_pasa_a(&self, hoy: &str) -> Result<Option<CorteListo>, ErrorBase> {
        let corte: Option<(i64, String, String, i64)> = self
            .con
            .query_row(
                "SELECT id, fecha, hora, ultima_venta_id FROM cortes_caja WHERE fecha < ?1 ORDER BY id DESC LIMIT 1",
                params![hoy],
                |f| Ok((f.get(0)?, f.get(1)?, f.get(2)?, f.get(3)?)),
            )
            .optional()?;
        let Some((id, fecha, hora, ultima_venta)) = corte else { return Ok(None) };
        let ventas_despues: i64 =
            self.con.query_row("SELECT count(*) FROM ventas WHERE id > ?1 AND fecha < ?2", params![ultima_venta, hoy], |f| f.get(0))?;
        if ventas_despues > 0 {
            return Ok(None);
        }
        Ok(Some(CorteListo { id, total: self.total_del_corte(id)?, fecha, hora }))
    }

    fn total_del_corte(&self, corte_id: i64) -> Result<f64, ErrorBase> {
        Ok(self.con.query_row(
            "SELECT COALESCE(SUM(denominacion * cantidad), 0) FROM cortes_caja_cambio WHERE corte_id = ?1",
            params![corte_id],
            |f| f.get(0),
        )?)
    }

    /// Las filas del cambio que dejó un corte (una por denominación), a la hora del corte.
    fn cambio_del_corte(&self, corte_id: i64, hora: &str) -> Result<Vec<FilaVentas>, ErrorBase> {
        let mut consulta = self.con.prepare("SELECT tipo, denominacion, cantidad FROM cortes_caja_cambio WHERE corte_id = ?1 ORDER BY id")?;
        let filas = consulta.query_map(params![corte_id], |f| {
            let (tipo, denominacion, cantidad): (String, f64, i64) = (f.get(0)?, f.get(1)?, f.get(2)?);
            Ok(FilaVentas {
                hora: hora.to_string(),
                producto: producto_de_cambio(&tipo),
                precio: Some(denominacion),
                cantidad: Some(cantidad),
                subtotal: Some(denominacion * cantidad as f64),
                tarjeta: false,
            })
        })?;
        Ok(filas.collect::<Result<_, _>>()?)
    }

    /// El corte con el que empieza el día `hoy`: el último de hoy o, si hoy no hay, el de un día
    /// anterior que pasó a hoy (`ventas_de_hoy`). Con quién lo hizo y su verificación, si la hay.
    pub fn corte_de_hoy(&self, hoy: &str) -> Result<Option<CorteDelDia>, ErrorBase> {
        let de_hoy: Option<i64> = self
            .con
            .query_row("SELECT id FROM cortes_caja WHERE fecha = ?1 ORDER BY id DESC LIMIT 1", params![hoy], |f| f.get(0))
            .optional()?;
        let id = match de_hoy {
            Some(id) => id,
            None => match self.corte_que_pasa_a(hoy)? {
                Some(c) => c.id,
                None => return Ok(None),
            },
        };
        let (fecha, hora, usuario): (String, String, Option<String>) = self.con.query_row(
            "SELECT c.fecha, c.hora, u.nombre_usuario FROM cortes_caja c
             LEFT JOIN sesiones_sistema s ON s.id = c.sesion_id LEFT JOIN usuarios_sistema u ON u.id = s.usuario_id
             WHERE c.id = ?1",
            params![id],
            |f| Ok((f.get(0)?, f.get(1)?, f.get(2)?)),
        )?;
        let verificacion = self
            .con
            .query_row(
                "SELECT v.fecha || ' ' || v.hora, v.contado, u.nombre_usuario FROM verificaciones_corte v
                 LEFT JOIN sesiones_sistema s ON s.id = v.sesion_id LEFT JOIN usuarios_sistema u ON u.id = s.usuario_id
                 WHERE v.corte_id = ?1 ORDER BY v.id DESC LIMIT 1",
                params![id],
                |f| Ok(Verificacion { en: f.get(0)?, contado: f.get(1)?, usuario: f.get(2)? }),
            )
            .optional()?;
        Ok(Some(CorteDelDia { id, fecha, hora, total: self.total_del_corte(id)?, usuario, verificacion }))
    }

    /// La empleada verifica el corte: cuánto contó de cambio. Queda registrado y como evento en
    /// VENTAS REALIZADAS ("CORTE VERIFICADO: CUADRA", "…: FALTAN $30.00", "…: SOBRAN $20.00").
    pub fn verificar_corte(&mut self, corte_id: i64, contado: f64, momento: &Momento, sesion_id: Option<i64>) -> Result<String, ErrorBase> {
        let esperado = self.total_del_corte(corte_id)?;
        let diferencia = contado - esperado;
        let evento = if diferencia.abs() < 0.005 {
            "CORTE VERIFICADO: CUADRA".to_string()
        } else if diferencia < 0.0 {
            format!("CORTE VERIFICADO: FALTAN {}", crate::corte::dinero(-diferencia))
        } else {
            format!("CORTE VERIFICADO: SOBRAN {}", crate::corte::dinero(diferencia))
        };
        let detalle = format!("Esperado {}, contado {}.", crate::corte::dinero(esperado), crate::corte::dinero(contado));
        let tx = self.con.transaction()?;
        tx.execute(
            "INSERT INTO eventos_especiales (fecha, hora, evento, detalle, sesion_id) VALUES (?1, ?2, ?3, ?4, ?5)",
            params![momento.fecha, momento.hora, evento, detalle, sesion_id],
        )?;
        let evento_id = tx.last_insert_rowid();
        tx.execute(
            "INSERT INTO verificaciones_corte (corte_id, fecha, hora, sesion_id, esperado, contado, evento_id) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            params![corte_id, momento.fecha, momento.hora, sesion_id, esperado, contado, evento_id],
        )?;
        tx.commit()?;
        Ok(evento)
    }

    /// El estado del corte para el botón CORTE DE CAJA: "listo" mientras nadie haya vendido después
    /// del último corte (una venta lo invalida y hay que volver a hacerlo).
    pub fn corte_listo(&self) -> Result<Option<CorteListo>, ErrorBase> {
        let corte: Option<(i64, String, String, i64)> = self
            .con
            .query_row("SELECT id, fecha, hora, ultima_venta_id FROM cortes_caja ORDER BY id DESC LIMIT 1", [], |f| {
                Ok((f.get(0)?, f.get(1)?, f.get(2)?, f.get(3)?))
            })
            .optional()?;
        let Some((id, fecha, hora, ultima_venta)) = corte else { return Ok(None) };
        let ventas_despues: i64 = self.con.query_row("SELECT count(*) FROM ventas WHERE id > ?1", params![ultima_venta], |f| f.get(0))?;
        if ventas_despues > 0 {
            return Ok(None);
        }
        Ok(Some(CorteListo { id, total: self.total_del_corte(id)?, fecha, hora }))
    }

    /// Los últimos `limite` días con ventas, del más reciente al más viejo.
    pub fn dias_con_ventas(&self, limite: u32) -> Result<Vec<String>, ErrorBase> {
        let mut consulta = self.con.prepare("SELECT DISTINCT fecha FROM ventas ORDER BY fecha DESC LIMIT ?1")?;
        let dias = consulta.query_map(params![limite], |f| f.get(0))?.collect::<Result<_, _>>()?;
        Ok(dias)
    }
}

#[cfg(test)]
mod pruebas {
    use super::*;

    #[test]
    fn el_corte_al_cerrar_pasa_al_dia_siguiente_si_nadie_vende_despues() {
        use crate::corte::PiezaCambio;
        let mut base = Base::en_memoria_v3().unwrap();
        let item = FilaCarrito { producto: "faja".into(), precio: 200.0, cantidad: 1, subtotal: 200.0 };
        let cambio = [PiezaCambio { tipo: "BILLETE".into(), denominacion: 100.0, cantidad: 3 }, PiezaCambio { tipo: "MONEDA".into(), denominacion: 1.0, cantidad: 40 }];
        assert_eq!(base.corte_listo().unwrap(), None, "sin cortes");
        base.registrar_venta(&[item.clone()], 200.0, 0.0, &Momento::nuevo("2026-11-24", "18:00:00"), None).unwrap();
        base.registrar_corte(&cambio, &Momento::nuevo("2026-11-24", "20:00:00"), None).unwrap();
        let listo = base.corte_listo().unwrap().expect("listo: nadie vendió después");
        assert_eq!((listo.fecha.as_str(), listo.total), ("2026-11-24", 340.0));
        // Al día siguiente, la tabla empieza con ese cambio, y las ventas de hoy van después.
        base.registrar_venta(&[item.clone()], 200.0, 0.0, &Momento::nuevo("2026-11-25", "10:00:00"), None).unwrap();
        let hoy = base.ventas_de_hoy("2026-11-25").unwrap();
        let productos: Vec<_> = hoy.iter().map(|f| f.producto.as_str()).collect();
        assert_eq!(productos, ["CAMBIO: BILLETE", "CAMBIO: MONEDA", "faja"]);
        assert_eq!(base.corte_listo().unwrap(), None, "ya se vendió después del corte");
        // Si se hubiera vendido después del corte ese mismo día, el corte ya no pasa.
        base.registrar_corte(&cambio, &Momento::nuevo("2026-11-25", "20:00:00"), None).unwrap();
        base.registrar_venta(&[item], 200.0, 0.0, &Momento::nuevo("2026-11-25", "20:30:00"), None).unwrap();
        let siguiente = base.ventas_de_hoy("2026-11-26").unwrap();
        assert!(siguiente.is_empty(), "el corte quedó invalidado por la venta de las 20:30");
        assert_eq!(base.corte_de_hoy("2026-11-26").unwrap(), None);
        // Pero el mismo día sigue siendo el punto de partida, aunque se venda después.
        let mismo_dia = base.corte_de_hoy("2026-11-25").unwrap().unwrap();
        assert_eq!(mismo_dia.total, 340.0);
    }

    #[test]
    fn la_empleada_verifica_el_corte_y_queda_en_ventas_realizadas() {
        use crate::corte::PiezaCambio;
        let mut base = Base::en_memoria_v3().unwrap();
        let cambio = [PiezaCambio { tipo: "BILLETE".into(), denominacion: 500.0, cantidad: 2 }];
        base.registrar_corte(&cambio, &Momento::nuevo("2026-11-24", "20:00:00"), None).unwrap();
        let corte = base.corte_de_hoy("2026-11-25").unwrap().expect("pasa al día siguiente");
        assert_eq!((corte.total, corte.verificacion.clone()), (1000.0, None));
        let evento = base.verificar_corte(corte.id, 970.0, &Momento::nuevo("2026-11-25", "09:00:00"), None).unwrap();
        assert_eq!(evento, "CORTE VERIFICADO: FALTAN $30.00");
        assert_eq!(base.corte_de_hoy("2026-11-25").unwrap().unwrap().verificacion.unwrap().contado, 970.0);
        let hoy: Vec<_> = base.ventas_de_hoy("2026-11-25").unwrap().into_iter().map(|f| f.producto).collect();
        assert_eq!(hoy, ["CAMBIO: BILLETE", "CORTE VERIFICADO: FALTAN $30.00"]);
        assert_eq!(base.verificar_corte(corte.id, 1000.0, &Momento::nuevo("2026-11-25", "09:05:00"), None).unwrap(), "CORTE VERIFICADO: CUADRA");
    }

    #[test]
    fn venta_con_tarjeta_queda_marcada_y_se_distingue_en_ventas_realizadas() {
        let mut base = Base::en_memoria_v3().unwrap();
        let item = |p: &str, precio: f64| FilaCarrito { producto: p.into(), precio, cantidad: 1, subtotal: precio };
        let m = Momento::nuevo("2026-11-26", "17:44:43");
        base.registrar_venta(&[item("conjunto", 250.0)], 250.0, 0.0, &m, None).unwrap();
        let id = base.registrar_venta_tarjeta(&[item("blusa de licra", 150.0)], &m, None).unwrap().unwrap();
        let (metodo, recibido): (String, f64) = base.con.query_row("SELECT metodo_pago, recibido FROM ventas WHERE id = ?1", params![id], |f| Ok((f.get(0)?, f.get(1)?))).unwrap();
        assert_eq!((metodo.as_str(), recibido), ("tarjeta", 150.0));
        let filas = base.ventas_de_hoy("2026-11-26").unwrap();
        let marcas: Vec<_> = filas.iter().map(|f| (f.producto.as_str(), f.tarjeta)).collect();
        assert_eq!(marcas, [("conjunto", false), ("blusa de licra", true)]);
    }

    #[test]
    fn venta_sin_ticket_recibe_el_total_sin_cambio_y_queda_marcada() {
        let mut base = Base::en_memoria_v3().unwrap();
        let item = FilaCarrito { producto: "faja".into(), precio: 200.0, cantidad: 2, subtotal: 400.0 };
        let m = Momento::nuevo("2026-11-25", "10:00:00");
        let normal = base.registrar_venta(&[item.clone()], 500.0, 100.0, &m, None).unwrap().unwrap();
        let rapida = base.registrar_venta_sin_ticket(&[item], &m, None).unwrap().unwrap();
        let fila = |id: i64| -> (f64, f64, i64) {
            base.con.query_row("SELECT recibido, cambio, sin_ticket FROM ventas WHERE id = ?1", params![id], |f| Ok((f.get(0)?, f.get(1)?, f.get(2)?))).unwrap()
        };
        assert_eq!(fila(normal), (500.0, 100.0, 0));
        assert_eq!(fila(rapida), (400.0, 0.0, 1));
    }
}
