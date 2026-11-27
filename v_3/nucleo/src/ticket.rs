//! Tickets ESC/POS: el de venta, el del corte de caja y la apertura del cajón, BYTE POR BYTE como
//! la v2 (`v_2/hardware/ticket_printer.py`; se comprueba contra `pruebas_v2/tickets_v2.json`).
//!
//! Aquí solo se arman los bytes: escribirlos a la impresora es de la app. Los datos de la tienda
//! (encabezado con dirección y RFC, logo, QR) vienen de afuera (`Tienda`): el repositorio es público
//! y esos datos no van en el código.

use chrono::NaiveDateTime;

use crate::carrito::FilaCarrito;
use crate::corte::{PiezaCambio, dinero, texto_denominacion, total_del_cambio};

const ESC: u8 = 27;
const GS: u8 = 29;
/// Ancho del logo en bytes (384 puntos) y los renglones en blanco que se le agregan abajo.
const ANCHO_LOGO: usize = 48;
const MARGEN_LOGO: usize = 24;
const LINEA: &str = "--------------------------------";

/// Una imagen de 1 bit lista para `GS v 0`: renglones de `ancho_bytes` bytes, 1 = negro.
#[derive(Debug, Clone, PartialEq)]
pub struct Imagen {
    pub ancho_bytes: u16,
    pub alto: u16,
    pub datos: Vec<u8>,
}

/// Lo que el ticket dice de la tienda.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct Tienda {
    /// Nombre (título del ticket de corte).
    pub nombre: String,
    /// Las líneas bajo el logo del ticket de venta (dirección, RFC…).
    pub encabezado: Vec<String>,
    /// El logo: 48 bytes de ancho; si su largo no es múltiplo de 48, se toman 180 renglones (v2).
    pub logo: Option<Vec<u8>>,
    /// El QR del sitio web, ya dibujado.
    pub qr: Option<Imagen>,
}

/// La mitad alta de la página de códigos 850 (bytes 0x80–0xFF), del códec de Python.
const CP850_ALTA: &str = "\u{00c7}\u{00fc}\u{00e9}\u{00e2}\u{00e4}\u{00e0}\u{00e5}\u{00e7}\u{00ea}\u{00eb}\u{00e8}\u{00ef}\u{00ee}\u{00ec}\u{00c4}\u{00c5}\u{00c9}\u{00e6}\u{00c6}\u{00f4}\u{00f6}\u{00f2}\u{00fb}\u{00f9}\u{00ff}\u{00d6}\u{00dc}\u{00f8}\u{00a3}\u{00d8}\u{00d7}\u{0192}\u{00e1}\u{00ed}\u{00f3}\u{00fa}\u{00f1}\u{00d1}\u{00aa}\u{00ba}\u{00bf}\u{00ae}\u{00ac}\u{00bd}\u{00bc}\u{00a1}\u{00ab}\u{00bb}\u{2591}\u{2592}\u{2593}\u{2502}\u{2524}\u{00c1}\u{00c2}\u{00c0}\u{00a9}\u{2563}\u{2551}\u{2557}\u{255d}\u{00a2}\u{00a5}\u{2510}\u{2514}\u{2534}\u{252c}\u{251c}\u{2500}\u{253c}\u{00e3}\u{00c3}\u{255a}\u{2554}\u{2569}\u{2566}\u{2560}\u{2550}\u{256c}\u{00a4}\u{00f0}\u{00d0}\u{00ca}\u{00cb}\u{00c8}\u{0131}\u{00cd}\u{00ce}\u{00cf}\u{2518}\u{250c}\u{2588}\u{2584}\u{00a6}\u{00cc}\u{2580}\u{00d3}\u{00df}\u{00d4}\u{00d2}\u{00f5}\u{00d5}\u{00b5}\u{00fe}\u{00de}\u{00da}\u{00db}\u{00d9}\u{00fd}\u{00dd}\u{00af}\u{00b4}\u{00ad}\u{00b1}\u{2017}\u{00be}\u{00b6}\u{00a7}\u{00f7}\u{00b8}\u{00b0}\u{00a8}\u{00b7}\u{00b9}\u{00b3}\u{00b2}\u{25a0}\u{00a0}";

/// Texto → CP850, como `str.encode("cp850", errors="replace")`: lo que no existe sale como `?`.
fn cp850(texto: &str) -> Vec<u8> {
    texto
        .chars()
        .map(|c| {
            if (c as u32) < 0x80 {
                c as u8
            } else {
                CP850_ALTA.chars().position(|x| x == c).map_or(b'?', |i| 0x80 + i as u8)
            }
        })
        .collect()
}

/// El buffer de un ticket, con los mismos pasos que `TicketPrinter` de la v2.
struct Buffer(Vec<u8>);

impl Buffer {
    /// `reset`: ESC @, sale del modo chino (FS .) y elige CP850 (ESC t 2).
    fn nuevo() -> Self {
        Self(vec![ESC, 64, 28, 46, ESC, 116, 2])
    }
    fn linea(&mut self, texto: &str) {
        self.0.extend(cp850(texto));
        self.0.push(b'\n');
    }
    fn alinear(&mut self, centro: bool) {
        self.0.extend([ESC, 97, u8::from(centro)]);
    }
    fn cajon(&mut self) {
        self.0.extend([ESC, 112, 0, 25, 250]);
    }
    /// `GS v 0` centrado.
    fn imagen(&mut self, ancho_bytes: usize, alto: usize, datos: &[u8]) {
        self.alinear(true);
        self.0.extend([GS, 118, 48, 0, (ancho_bytes & 0xFF) as u8, ((ancho_bytes >> 8) & 0xFF) as u8, (alto & 0xFF) as u8, ((alto >> 8) & 0xFF) as u8]);
        self.0.extend(datos);
        self.alinear(false);
    }
    fn logo(&mut self, logo: &[u8]) {
        if logo.is_empty() {
            return;
        }
        let alto = if logo.len() % ANCHO_LOGO == 0 { logo.len() / ANCHO_LOGO } else { 180 };
        let mut datos = logo[..(ANCHO_LOGO * alto).min(logo.len())].to_vec();
        datos.resize(ANCHO_LOGO * alto, 0);
        datos.extend(std::iter::repeat_n(0, ANCHO_LOGO * MARGEN_LOGO));
        self.imagen(ANCHO_LOGO, alto + MARGEN_LOGO, &datos);
    }
}

/// El ticket de una venta. `abrir_cajon`: la v2 siempre lo abre al imprimir; con tarjeta, no.
pub fn ticket_venta(tienda: &Tienda, items: &[FilaCarrito], total: f64, recibido: f64, cambio: f64, cuando: NaiveDateTime, abrir_cajon: bool) -> Vec<u8> {
    let mut b = Buffer::nuevo();
    if abrir_cajon {
        b.cajon();
    }
    if let Some(logo) = &tienda.logo {
        b.logo(logo);
    }
    for l in &tienda.encabezado {
        b.linea(l);
    }
    b.linea("");
    b.linea(&cuando.format("%d/%m/%Y  %H:%M:%S").to_string());
    b.linea(LINEA);
    for i in items {
        // En mayúsculas solo en el ticket (los nombres se capturan a mano).
        b.linea(&i.producto.to_uppercase());
        b.linea(&format!("  {} x ${:.2} = ${:.2}", i.cantidad, i.precio, i.subtotal));
    }
    b.linea(LINEA);
    b.linea(&format!("TOTAL: ${total:.2}"));
    b.linea(&format!("RECIBIDO: ${recibido:.2}"));
    b.linea(&format!("CAMBIO: ${cambio:.2}"));
    b.linea(LINEA);
    b.0.push(10);
    if let Some(qr) = &tienda.qr {
        b.imagen(qr.ancho_bytes as usize, qr.alto as usize, &qr.datos);
    }
    b.0.push(10);
    for _ in 0..3 {
        b.linea("");
    }
    b.0
}

/// El ticket del corte de caja: el cambio que queda en la caja.
pub fn ticket_corte(tienda: &Tienda, cambio: &[PiezaCambio], usuario: Option<&str>, cuando: NaiveDateTime) -> Vec<u8> {
    let mut b = Buffer::nuevo();
    b.alinear(true);
    b.linea(&tienda.nombre);
    b.linea("CORTE DE CAJA");
    b.alinear(false);
    b.linea(LINEA);
    b.linea(&cuando.format("Fecha: %d/%m/%Y").to_string());
    b.linea(&cuando.format("Hora:  %H:%M:%S").to_string());
    if let Some(u) = usuario {
        b.linea(&format!("Hizo el corte: {u}"));
    }
    b.linea(LINEA);
    b.linea("CAMBIO QUE QUEDA EN LA CAJA");
    for p in cambio.iter().filter(|p| p.cantidad != 0) {
        let subtotal = p.denominacion * p.cantidad as f64;
        b.linea(&format!("{} x {} {} = {}", p.cantidad, p.tipo, texto_denominacion(p.denominacion), dinero(subtotal)));
    }
    b.linea(LINEA);
    b.linea(&format!("TOTAL CAMBIO: {}", dinero(total_del_cambio(cambio))));
    b.linea(LINEA);
    for _ in 0..3 {
        b.linea("");
    }
    b.0
}

/// Solo abrir el cajón (ABRIR CAJA, el corte, sin ticket).
pub fn abrir_cajon() -> Vec<u8> {
    let mut b = Buffer::nuevo();
    b.cajon();
    b.0
}

#[cfg(test)]
mod pruebas {
    use super::*;
    use chrono::NaiveDate;
    use serde_json::Value;

    fn hex(s: &str) -> Vec<u8> {
        (0..s.len()).step_by(2).map(|i| u8::from_str_radix(&s[i..i + 2], 16).unwrap()).collect()
    }

    /// Los bytes de la v2 contra los de la v3, ticket por ticket (con encabezado, logo y QR de prueba).
    #[test]
    fn tickets_identicos_a_la_v2() {
        let casos: Value = serde_json::from_str(include_str!("../pruebas_v2/tickets_v2.json")).unwrap();
        let qr = &casos["qr"];
        let tienda = Tienda {
            nombre: "Yaeli's Boutique".into(),
            encabezado: casos["encabezado"].as_array().unwrap().iter().map(|l| l.as_str().unwrap().to_string()).collect(),
            logo: Some(hex(casos["logo_hex"].as_str().unwrap())),
            qr: Some(Imagen { ancho_bytes: qr["ancho_bytes"].as_u64().unwrap() as u16, alto: qr["alto"].as_u64().unwrap() as u16, datos: hex(qr["hex"].as_str().unwrap()) }),
        };
        let cuando = NaiveDate::from_ymd_opt(2026, 11, 26).unwrap().and_hms_opt(17, 44, 3).unwrap();
        for v in casos["ventas"].as_array().unwrap() {
            let items: Vec<FilaCarrito> = v["items"]
                .as_array()
                .unwrap()
                .iter()
                .map(|i| FilaCarrito { producto: i[0].as_str().unwrap().into(), precio: i[1].as_f64().unwrap(), cantidad: i[2].as_i64().unwrap(), subtotal: i[3].as_f64().unwrap() })
                .collect();
            let v3 = ticket_venta(&tienda, &items, v["total"].as_f64().unwrap(), v["recibido"].as_f64().unwrap(), v["cambio"].as_f64().unwrap(), cuando, true);
            assert_eq!(v3, hex(v["hex"].as_str().unwrap()), "venta {:?}", v["items"]);
        }
        for c in casos["cortes"].as_array().unwrap() {
            let cambio: Vec<PiezaCambio> = c["cambio"]
                .as_array()
                .unwrap()
                .iter()
                .map(|p| PiezaCambio { tipo: p[0].as_str().unwrap().into(), denominacion: p[1].as_f64().unwrap(), cantidad: p[2].as_i64().unwrap() })
                .collect();
            let v3 = ticket_corte(&tienda, &cambio, c["usuario"].as_str(), cuando);
            assert_eq!(v3, hex(c["hex"].as_str().unwrap()), "corte {:?}", c["cambio"]);
        }
        assert_eq!(abrir_cajon(), hex(casos["cajon_hex"].as_str().unwrap()));
    }

    #[test]
    fn con_tarjeta_el_ticket_no_abre_el_cajon_y_sin_logo_ni_qr_tambien_sale() {
        let cuando = NaiveDate::from_ymd_opt(2026, 11, 26).unwrap().and_hms_opt(9, 0, 0).unwrap();
        let item = [FilaCarrito { producto: "faja".into(), precio: 200.0, cantidad: 1, subtotal: 200.0 }];
        let t = ticket_venta(&Tienda::default(), &item, 200.0, 200.0, 0.0, cuando, false);
        assert!(!t.windows(2).any(|w| w == [ESC, 112]), "sin ESC p");
        assert!(t.windows(4).any(|w| w == b"FAJA"));
        assert_eq!(cp850("ñ€"), [0xA4, b'?']);
    }
}
