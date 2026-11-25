//! Corte de caja: el cambio que se deja en la caja (`v_2/services/corte_caja.py`).

pub const BILLETE: &str = "BILLETE";
pub const MONEDA: &str = "MONEDA";

/// Las denominaciones en el orden del diálogo, del ticket y de la tabla de ventas.
pub const DENOMINACIONES: &[(&str, f64)] = &[
    (BILLETE, 500.0),
    (BILLETE, 200.0),
    (BILLETE, 100.0),
    (BILLETE, 50.0),
    (BILLETE, 20.0),
    (MONEDA, 20.0),
    (MONEDA, 10.0),
    (MONEDA, 5.0),
    (MONEDA, 2.0),
    (MONEDA, 1.0),
    (MONEDA, 0.5),
];

/// Nombre del evento que deja un corte en el historial.
pub const EVENTO_CORTE: &str = "CORTE DE CAJA";

/// Lo que dice la columna PRODUCTO en una fila del cambio ("CAMBIO: BILLETE").
pub fn producto_de_cambio(tipo: &str) -> String {
    format!("CAMBIO: {tipo}")
}

/// 500 → "$500", 0.5 → "$0.50".
pub fn texto_denominacion(denominacion: f64) -> String {
    if denominacion.fract() == 0.0 { format!("${}", denominacion as i64) } else { format!("${denominacion:.2}") }
}

/// Una pieza del cambio: tipo, denominación y cantidad.
#[derive(Debug, Clone, PartialEq)]
pub struct PiezaCambio {
    pub tipo: String,
    pub denominacion: f64,
    pub cantidad: i64,
}

pub fn total_del_cambio(cambio: &[PiezaCambio]) -> f64 {
    cambio.iter().map(|p| p.denominacion * p.cantidad as f64).sum()
}

/// "2 x BILLETE $500, 3 x MONEDA $10 = $1,030.00" (como `resumen_del_cambio` de la v2).
pub fn resumen_del_cambio(cambio: &[PiezaCambio]) -> String {
    let partes: Vec<String> = cambio
        .iter()
        .filter(|p| p.cantidad != 0)
        .map(|p| format!("{} x {} {}", p.cantidad, p.tipo, texto_denominacion(p.denominacion)))
        .collect();
    let total = dinero(total_del_cambio(cambio));
    if partes.is_empty() { format!("Sin cambio ({total})") } else { format!("{} = {total}", partes.join(", ")) }
}

/// "$1,030.00": dos decimales y separador de miles (como `f"${x:,.2f}"` en Python).
pub fn dinero(valor: f64) -> String {
    let texto = format!("{:.2}", valor.abs());
    let (entero, decimales) = texto.split_once('.').unwrap_or((&texto, "00"));
    let mut con_comas = String::new();
    for (i, c) in entero.chars().enumerate() {
        if i > 0 && (entero.len() - i) % 3 == 0 {
            con_comas.push(',');
        }
        con_comas.push(c);
    }
    format!("{}${con_comas}.{decimales}", if valor < 0.0 { "-" } else { "" })
}

/// Cuántas piezas de una denominación se escribieron: vacío es 0; si no es un entero >= 0, `None`
/// (como `leer_cantidad` de la v2).
pub fn leer_cantidad(texto: &str) -> Option<i64> {
    let limpio = texto.trim();
    if limpio.is_empty() {
        return Some(0);
    }
    limpio.parse::<i64>().ok().filter(|c| *c >= 0)
}

/// Lo escrito para cada denominación, en el orden de `DENOMINACIONES`, convertido en el cambio. Si
/// algo no es válido, el mensaje para el usuario (los mismos textos que la v2).
pub fn leer_cambio(textos: &[String]) -> Result<Vec<PiezaCambio>, String> {
    if textos.len() != DENOMINACIONES.len() {
        return Err(format!("Se esperaban {} cantidades y llegaron {}.", DENOMINACIONES.len(), textos.len()));
    }
    DENOMINACIONES
        .iter()
        .zip(textos)
        .map(|(&(tipo, denominacion), texto)| match leer_cantidad(texto) {
            Some(cantidad) => Ok(PiezaCambio { tipo: tipo.to_string(), denominacion, cantidad }),
            None => Err(format!(
                "La cantidad de {}s de {} no es válida: escriba cuántas piezas hay (un número entero) o déjelo vacío.",
                tipo.to_lowercase(),
                texto_denominacion(denominacion)
            )),
        })
        .collect()
}

#[cfg(test)]
mod pruebas {
    use super::*;

    #[test]
    fn leer_el_cambio_como_la_v2() {
        let mut textos = vec![String::new(); DENOMINACIONES.len()];
        textos[0] = " 2 ".into();
        textos[6] = "3".into();
        let cambio = leer_cambio(&textos).unwrap();
        assert_eq!(total_del_cambio(&cambio), 1030.0);
        assert_eq!(resumen_del_cambio(&cambio), "2 x BILLETE $500, 3 x MONEDA $10 = $1,030.00");
        textos[10] = "-1".into();
        assert_eq!(
            leer_cambio(&textos).unwrap_err(),
            "La cantidad de monedas de $0.50 no es válida: escriba cuántas piezas hay (un número entero) o déjelo vacío."
        );
        textos[10] = "1.5".into();
        assert!(leer_cambio(&textos).is_err());
        assert_eq!(leer_cantidad(""), Some(0));
    }

    #[test]
    fn textos() {
        assert_eq!(texto_denominacion(500.0), "$500");
        assert_eq!(texto_denominacion(0.5), "$0.50");
        assert_eq!(dinero(1030.0), "$1,030.00");
        assert_eq!(dinero(1234567.891), "$1,234,567.89");
        assert_eq!(producto_de_cambio(BILLETE), "CAMBIO: BILLETE");
    }
}
