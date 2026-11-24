//! Cobro: leer el monto que se escribe y comprobar que alcance (`v_2/dialogs/parseo.py` y
//! `v_2/dialogs/cobro_uno.py`).

/// Lee un monto como la v2 (`parse_monto`): quita los espacios y acepta "1,234.50", "1.234,50",
/// "12,5" o "12.5". Si hay coma y punto, el separador decimal es el que va más a la derecha.
/// Como en la v2, acepta lo que acepte `float()` de Python, incluidos negativos y "1e3": el cobro
/// los rechaza después si no alcanzan.
pub fn leer_monto(texto: &str) -> Option<f64> {
    let mut limpio: String = texto.chars().filter(|c| !c.is_whitespace()).collect();
    if limpio.is_empty() {
        return None;
    }
    match (limpio.rfind(','), limpio.rfind('.')) {
        (Some(coma), Some(punto)) if coma > punto => limpio = limpio.replace('.', "").replace(',', "."),
        (Some(_), Some(_)) => limpio = limpio.replace(',', ""),
        (Some(_), None) => limpio = limpio.replace(',', "."),
        _ => {}
    }
    limpio.parse::<f64>().ok().filter(|v| v.is_finite())
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Cobro {
    pub total: f64,
    pub recibido: f64,
    pub cambio: f64,
}

#[derive(Debug, Clone, PartialEq, thiserror::Error)]
pub enum ErrorCobro {
    /// Mismo texto que la v2.
    #[error("El monto ingresado no es válido. Usa solo números y, si hace falta, coma o punto decimal.")]
    MontoInvalido,
    #[error("El monto recibido es menor al total. Faltan ${faltan:.2}.")]
    NoAlcanza { faltan: f64 },
}

impl Cobro {
    /// Cobra `total` con lo que se escribió. Vacío = pago exacto (la caja de la v3 lo permite con
    /// Intro sin escribir; en la v2 el diálogo no lo aceptaba).
    pub fn con_texto(total: f64, texto: &str) -> Result<Self, ErrorCobro> {
        if texto.trim().is_empty() {
            return Ok(Self::exacto(total));
        }
        let recibido = leer_monto(texto).ok_or(ErrorCobro::MontoInvalido)?;
        Self::nuevo(total, recibido)
    }

    pub fn nuevo(total: f64, recibido: f64) -> Result<Self, ErrorCobro> {
        if recibido < total {
            return Err(ErrorCobro::NoAlcanza { faltan: total - recibido });
        }
        Ok(Self { total, recibido, cambio: recibido - total })
    }

    /// Pago exacto (también el cobro rápido sin ticket de D15: recibido = total, cambio 0).
    pub fn exacto(total: f64) -> Self {
        Self { total, recibido: total, cambio: 0.0 }
    }
}

#[cfg(test)]
mod pruebas {
    use super::*;

    #[test]
    fn cobro_alcanza_y_da_cambio() {
        assert_eq!(Cobro::con_texto(430.0, "500").unwrap().cambio, 70.0);
        assert_eq!(Cobro::con_texto(430.0, "").unwrap(), Cobro::exacto(430.0));
        assert_eq!(Cobro::con_texto(430.0, "400"), Err(ErrorCobro::NoAlcanza { faltan: 30.0 }));
        assert_eq!(Cobro::con_texto(430.0, "abc"), Err(ErrorCobro::MontoInvalido));
        assert_eq!(Cobro::con_texto(430.0, "-5"), Err(ErrorCobro::NoAlcanza { faltan: 435.0 }));
    }

    #[test]
    fn mensajes_como_la_v2() {
        assert_eq!(ErrorCobro::NoAlcanza { faltan: 30.0 }.to_string(), "El monto recibido es menor al total. Faltan $30.00.");
    }
}
