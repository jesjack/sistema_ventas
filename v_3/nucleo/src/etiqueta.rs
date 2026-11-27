//! Etiquetas de código de barras para la NIIMBOT B1, como la v2 (`v_2/hardware/barcode_printer.py`
//! y la librería `niimprint`): Code 128, la etiqueta vertical de 3 piezas para recortar y el
//! protocolo de la impresora. Solo arma imágenes y bytes; el puerto serie es de la app.
//!
//! Se prueba contra `pruebas_v2/etiquetas_v2.json` (código real de la v2): los módulos de Code 128,
//! las imágenes (pixel por pixel, también el texto: FreeType como PIL) y los paquetes son idénticos.
//!
//! Solo Code 128 en vertical: en la base real, las 106 impresiones son así (2026-11-26).

use std::time::Duration;

// ---- Code 128 (transcrito de python-barcode 0.16.1, `barcode/codex.py`) ------------------------

// GENERADO desde python-barcode 0.16.1 (barcode/charsets/code128.py): no editar a mano.
/// Patrón de módulos de cada valor.
const PATRONES: [&str; 106] = ["11011001100", "11001101100", "11001100110", "10010011000", "10010001100", "10001001100", "10011001000", "10011000100", "10001100100", "11001001000", "11001000100", "11000100100", "10110011100", "10011011100", "10011001110", "10111001100", "10011101100", "10011100110", "11001110010", "11001011100", "11001001110", "11011100100", "11001110100", "11101101110", "11101001100", "11100101100", "11100100110", "11101100100", "11100110100", "11100110010", "11011011000", "11011000110", "11000110110", "10100011000", "10001011000", "10001000110", "10110001000", "10001101000", "10001100010", "11010001000", "11000101000", "11000100010", "10110111000", "10110001110", "10001101110", "10111011000", "10111000110", "10001110110", "11101110110", "11010001110", "11000101110", "11011101000", "11011100010", "11011101110", "11101011000", "11101000110", "11100010110", "11101101000", "11101100010", "11100011010", "11101111010", "11001000010", "11110001010", "10100110000", "10100001100", "10010110000", "10010000110", "10000101100", "10000100110", "10110010000", "10110000100", "10011010000", "10011000010", "10000110100", "10000110010", "11000010010", "11001010000", "11110111010", "11000010100", "10001111010", "10100111100", "10010111100", "10010011110", "10111100100", "10011110100", "10011110010", "11110100100", "11110010100", "11110010010", "11011011110", "11011110110", "11110110110", "10101111000", "10100011110", "10001011110", "10111101000", "10111100010", "11110101000", "11110100010", "10111011110", "10111101110", "11101011110", "11110101110", "11010000100", "11010010000", "11010011100"];
const PARADA: &str = "11000111010";
const INICIO: [(char, u8); 3] = [('A', 103), ('B', 104), ('C', 105)];
/// Un cambio de juego justo después del inicio se fusiona en el inicio (TO).
const FUSIONAR: [(u8, u8); 3] = [(99, 105), (100, 104), (101, 103)];
const JUEGO_A: [(char, u8); 100] = [('\u{0000}', 64), ('\u{0001}', 65), ('\u{0002}', 66), ('\u{0003}', 67), ('\u{0004}', 68), ('\u{0005}', 69), ('\u{0006}', 70), ('\u{0007}', 71), ('\u{0008}', 72), ('\u{0009}', 73), ('\u{000a}', 74), ('\u{000b}', 75), ('\u{000c}', 76), ('\u{000d}', 77), ('\u{000e}', 78), ('\u{000f}', 79), ('\u{0010}', 80), ('\u{0011}', 81), ('\u{0012}', 82), ('\u{0013}', 83), ('\u{0014}', 84), ('\u{0015}', 85), ('\u{0016}', 86), ('\u{0017}', 87), ('\u{0018}', 88), ('\u{0019}', 89), ('\u{001a}', 90), ('\u{001b}', 91), ('\u{001c}', 92), ('\u{001d}', 93), ('\u{001e}', 94), ('\u{001f}', 95), ('\u{0020}', 0), ('\u{0021}', 1), ('\u{0022}', 2), ('\u{0023}', 3), ('\u{0024}', 4), ('\u{0025}', 5), ('\u{0026}', 6), ('\u{0027}', 7), ('\u{0028}', 8), ('\u{0029}', 9), ('\u{002a}', 10), ('\u{002b}', 11), ('\u{002c}', 12), ('\u{002d}', 13), ('\u{002e}', 14), ('\u{002f}', 15), ('\u{0030}', 16), ('\u{0031}', 17), ('\u{0032}', 18), ('\u{0033}', 19), ('\u{0034}', 20), ('\u{0035}', 21), ('\u{0036}', 22), ('\u{0037}', 23), ('\u{0038}', 24), ('\u{0039}', 25), ('\u{003a}', 26), ('\u{003b}', 27), ('\u{003c}', 28), ('\u{003d}', 29), ('\u{003e}', 30), ('\u{003f}', 31), ('\u{0040}', 32), ('\u{0041}', 33), ('\u{0042}', 34), ('\u{0043}', 35), ('\u{0044}', 36), ('\u{0045}', 37), ('\u{0046}', 38), ('\u{0047}', 39), ('\u{0048}', 40), ('\u{0049}', 41), ('\u{004a}', 42), ('\u{004b}', 43), ('\u{004c}', 44), ('\u{004d}', 45), ('\u{004e}', 46), ('\u{004f}', 47), ('\u{0050}', 48), ('\u{0051}', 49), ('\u{0052}', 50), ('\u{0053}', 51), ('\u{0054}', 52), ('\u{0055}', 53), ('\u{0056}', 54), ('\u{0057}', 55), ('\u{0058}', 56), ('\u{0059}', 57), ('\u{005a}', 58), ('\u{005b}', 59), ('\u{005c}', 60), ('\u{005d}', 61), ('\u{005e}', 62), ('\u{005f}', 63), ('\u{00f1}', 102), ('\u{00f2}', 97), ('\u{00f3}', 96), ('\u{00f4}', 101)];
const JUEGO_A_TO: [(char, u8); 3] = [('T', 98), ('B', 100), ('C', 99)];
const JUEGO_B: [(char, u8); 100] = [('\u{0020}', 0), ('\u{0021}', 1), ('\u{0022}', 2), ('\u{0023}', 3), ('\u{0024}', 4), ('\u{0025}', 5), ('\u{0026}', 6), ('\u{0027}', 7), ('\u{0028}', 8), ('\u{0029}', 9), ('\u{002a}', 10), ('\u{002b}', 11), ('\u{002c}', 12), ('\u{002d}', 13), ('\u{002e}', 14), ('\u{002f}', 15), ('\u{0030}', 16), ('\u{0031}', 17), ('\u{0032}', 18), ('\u{0033}', 19), ('\u{0034}', 20), ('\u{0035}', 21), ('\u{0036}', 22), ('\u{0037}', 23), ('\u{0038}', 24), ('\u{0039}', 25), ('\u{003a}', 26), ('\u{003b}', 27), ('\u{003c}', 28), ('\u{003d}', 29), ('\u{003e}', 30), ('\u{003f}', 31), ('\u{0040}', 32), ('\u{0041}', 33), ('\u{0042}', 34), ('\u{0043}', 35), ('\u{0044}', 36), ('\u{0045}', 37), ('\u{0046}', 38), ('\u{0047}', 39), ('\u{0048}', 40), ('\u{0049}', 41), ('\u{004a}', 42), ('\u{004b}', 43), ('\u{004c}', 44), ('\u{004d}', 45), ('\u{004e}', 46), ('\u{004f}', 47), ('\u{0050}', 48), ('\u{0051}', 49), ('\u{0052}', 50), ('\u{0053}', 51), ('\u{0054}', 52), ('\u{0055}', 53), ('\u{0056}', 54), ('\u{0057}', 55), ('\u{0058}', 56), ('\u{0059}', 57), ('\u{005a}', 58), ('\u{005b}', 59), ('\u{005c}', 60), ('\u{005d}', 61), ('\u{005e}', 62), ('\u{005f}', 63), ('\u{0060}', 64), ('\u{0061}', 65), ('\u{0062}', 66), ('\u{0063}', 67), ('\u{0064}', 68), ('\u{0065}', 69), ('\u{0066}', 70), ('\u{0067}', 71), ('\u{0068}', 72), ('\u{0069}', 73), ('\u{006a}', 74), ('\u{006b}', 75), ('\u{006c}', 76), ('\u{006d}', 77), ('\u{006e}', 78), ('\u{006f}', 79), ('\u{0070}', 80), ('\u{0071}', 81), ('\u{0072}', 82), ('\u{0073}', 83), ('\u{0074}', 84), ('\u{0075}', 85), ('\u{0076}', 86), ('\u{0077}', 87), ('\u{0078}', 88), ('\u{0079}', 89), ('\u{007a}', 90), ('\u{007b}', 91), ('\u{007c}', 92), ('\u{007d}', 93), ('\u{007e}', 94), ('\u{007f}', 95), ('\u{00f1}', 102), ('\u{00f2}', 97), ('\u{00f3}', 96), ('\u{00f4}', 100)];
const JUEGO_B_TO: [(char, u8); 3] = [('T', 98), ('A', 101), ('C', 99)];
const JUEGO_C: [(char, u8); 1] = [('\u{00f1}', 102)];
const JUEGO_C_TO: [(char, u8); 2] = [('A', 101), ('B', 100)];

fn valor(tabla: &[(char, u8)], c: char) -> Option<u8> {
    tabla.iter().find(|(k, _)| *k == c).map(|(_, v)| *v)
}

#[derive(Clone, Copy, PartialEq)]
enum Juego {
    A,
    B,
    C,
}

struct Codificador {
    juego: Juego,
    pendiente: Option<char>,
}

impl Codificador {
    fn tabla(&self) -> (&'static [(char, u8)], &'static [(char, u8)]) {
        match self.juego {
            Juego::A => (&JUEGO_A, &JUEGO_A_TO),
            Juego::B => (&JUEGO_B, &JUEGO_B_TO),
            Juego::C => (&JUEGO_C, &JUEGO_C_TO),
        }
    }
    /// `_new_charset`: el valor de cambio (en el juego ACTUAL) y el cambio.
    fn cambiar(&mut self, a: Juego) -> u8 {
        let letra = match a {
            Juego::A => 'A',
            Juego::B => 'B',
            Juego::C => 'C',
        };
        let v = valor(self.tabla().1, letra).expect("cambio de juego");
        self.juego = a;
        v
    }
    /// `_convert`: el valor del carácter; en C, los dígitos van de dos en dos.
    fn convertir(&mut self, c: char) -> Result<Option<u8>, String> {
        let (tabla, _) = self.tabla();
        if self.juego != Juego::C {
            return valor(tabla, c).map(Some).ok_or_else(|| format!("el carácter {c:?} no existe en Code 128"));
        }
        if let Some(v) = valor(tabla, c) {
            return Ok(Some(v));
        }
        if c.is_ascii_digit() {
            match self.pendiente.take() {
                Some(primero) => return Ok(Some(((primero as u8 - b'0') * 10 + (c as u8 - b'0')) as u8)),
                None => {
                    self.pendiente = Some(c);
                    return Ok(None);
                }
            }
        }
        Err(format!("el carácter {c:?} no se puede convertir"))
    }
}

/// El patrón de módulos (`1` = barra) de un código, idéntico al de `Code128.build()` de la v2.
pub fn code128(texto: &str) -> Result<String, String> {
    if texto.is_empty() {
        return Err("Escriba el código.".into());
    }
    let caracteres: Vec<char> = texto.chars().collect();
    if let Some(c) = caracteres.iter().find(|c| valor(&JUEGO_A, **c).is_none() && valor(&JUEGO_B, **c).is_none() && valor(&JUEGO_C, **c).is_none()) {
        return Err(format!("Code 128 no acepta el código '{texto}': el carácter {c:?} no existe en Code 128."));
    }
    let mut cod = Codificador { juego: Juego::C, pendiente: None };
    let mut valores: Vec<u8> = vec![valor(&INICIO, 'C').expect("inicio")];
    for (pos, &c) in caracteres.iter().enumerate() {
        // `_maybe_switch_charset`
        let siguientes = &caracteres[pos..(pos + 10).min(caracteres.len())];
        let muchos_digitos = siguientes.iter().take_while(|c| c.is_ascii_digit()).count() > 3;
        match cod.juego {
            Juego::C if !c.is_ascii_digit() => {
                if valor(&JUEGO_B, c).is_some() {
                    valores.push(cod.cambiar(Juego::B));
                } else if valor(&JUEGO_A, c).is_some() {
                    valores.push(cod.cambiar(Juego::A));
                }
                if let Some(p) = cod.pendiente.take() {
                    valores.extend(cod.convertir(p)?);
                }
            }
            Juego::B => {
                if muchos_digitos {
                    valores.push(cod.cambiar(Juego::C));
                } else if valor(&JUEGO_B, c).is_none() && valor(&JUEGO_A, c).is_some() {
                    valores.push(cod.cambiar(Juego::A));
                }
            }
            Juego::A => {
                if muchos_digitos {
                    valores.push(cod.cambiar(Juego::C));
                } else if valor(&JUEGO_A, c).is_none() && valor(&JUEGO_B, c).is_some() {
                    valores.push(cod.cambiar(Juego::B));
                }
            }
            Juego::C => {}
        }
        valores.extend(cod.convertir(c)?);
    }
    if let Some(p) = cod.pendiente.take() {
        valores.push(cod.cambiar(Juego::B));
        valores.extend(cod.convertir(p)?);
    }
    // `_try_to_optimize`: un cambio justo después del inicio se vuelve el inicio de ese juego.
    if let Some(&(_, inicio)) = valores.get(1).and_then(|v| FUSIONAR.iter().find(|(k, _)| k == v)) {
        valores.splice(0..2, [inicio]);
    }
    let suma = valores.iter().enumerate().map(|(i, v)| if i == 0 { *v as usize } else { i * *v as usize }).sum::<usize>() % 103;
    valores.push(suma as u8);
    let mut modulos: String = valores.iter().map(|v| PATRONES[*v as usize]).collect();
    modulos.push_str(PARADA);
    modulos.push_str("11");
    Ok(modulos)
}

// ---- La imagen ------------------------------------------------------------------------------

/// Una imagen en blanco y negro (true = negro), por renglones.
#[derive(Debug, Clone, PartialEq)]
pub struct Mapa {
    pub ancho: usize,
    pub alto: usize,
    pub negro: Vec<bool>,
}

impl Mapa {
    pub fn blanco(ancho: usize, alto: usize) -> Self {
        Self { ancho, alto, negro: vec![false; ancho * alto] }
    }
    pub fn en(&self, x: usize, y: usize) -> bool {
        self.negro[y * self.ancho + x]
    }
    fn pintar(&mut self, x: i64, y: i64) {
        if x >= 0 && y >= 0 && (x as usize) < self.ancho && (y as usize) < self.alto {
            self.negro[y as usize * self.ancho + x as usize] = true;
        }
    }
    fn rectangulo(&mut self, x0: i64, y0: i64, x1: i64, y1: i64) {
        for y in y0..=y1 {
            for x in x0..=x1 {
                self.pintar(x, y);
            }
        }
    }
    fn pegar(&mut self, otro: &Mapa, x0: usize, y0: usize) {
        for y in 0..otro.alto {
            for x in 0..otro.ancho {
                if x0 + x < self.ancho && y0 + y < self.alto {
                    self.negro[(y0 + y) * self.ancho + x0 + x] = otro.en(x, y);
                }
            }
        }
    }
    /// Girada 90° a la izquierda (como `Image.rotate(90, expand=True)` de PIL).
    pub fn girada_izquierda(&self) -> Mapa {
        let mut g = Mapa::blanco(self.alto, self.ancho);
        for y in 0..g.alto {
            for x in 0..g.ancho {
                g.negro[y * g.ancho + x] = self.en(self.ancho - 1 - y, x);
            }
        }
        g
    }
}

/// La fuente de la v2 (la que trae python-barcode), para el texto bajo las barras.
const FUENTE: &[u8] = include_bytes!("../fuentes/DejaVuSansMono.ttf");
const TAMANO_TEXTO_PX: u32 = 18;
const SEPARACION_TEXTO_PX: usize = 3;
pub const ANCHO_PX: usize = 384;
pub const ALTO_PX: usize = 224;
const PX_POR_MM: usize = 8;
/// Arriba, derecha, abajo, izquierda (de la etiqueta en horizontal), como la v2.
pub const MARGENES: [usize; 4] = [3 * PX_POR_MM, 2 * PX_POR_MM, 0, 3 * PX_POR_MM];
pub const PIEZAS_POR_ETIQUETA: usize = 3;
const SEPARACION_PIEZAS_PX: usize = 3 * PX_POR_MM;

/// `round()` de Python: a la mitad, al par.
fn redondear(x: f64) -> i64 {
    let r = x.round();
    if (x - x.trunc()).abs() == 0.5 && (r as i64) % 2 != 0 { (r - x.signum()) as i64 } else { r as i64 }
}

/// Un texto rasterizado como lo hace PIL con `fontmode = "1"`: cada letra con FreeType en
/// monocromático (FT_LOAD_TARGET_MONO, render MONO), y las letras separadas por el avance SIN
/// hinting en 1/64 de píxel (10.84 px a 18 px, no 11), redondeando la posición de cada una, como
/// PIL. Los píxeles negros, con el origen en la línea de ascenso.
struct Texto {
    pixeles: Vec<(i64, i64)>,
    largo: f64,
}

impl Texto {
    fn nuevo(cara: &freetype::Face, texto: &str, tamano: u32) -> Result<Self, String> {
        cara.set_pixel_sizes(0, tamano).map_err(|e| e.to_string())?;
        let ascenso = cara.size_metrics().map_or(tamano as i64, |m| (m.ascender >> 6) as i64);
        // La pluma en 1/64 de píxel (26.6 de FreeType), como PIL: sumar en decimales se desvía.
        let (mut pixeles, mut pluma) = (Vec::new(), 0i64);
        for c in texto.chars() {
            cara.load_char(c as usize, freetype::face::LoadFlag::TARGET_MONO).map_err(|e| e.to_string())?;
            let glifo = cara.glyph();
            glifo.render_glyph(freetype::RenderMode::Mono).map_err(|e| e.to_string())?;
            let bitmap = glifo.bitmap();
            // La posición de la letra: la pluma redondeada (PIXEL de PIL: `((x + 32) & -64) >> 6`).
            let x = (pluma + 32).div_euclid(64);
            let (izq, arriba) = (x + glifo.bitmap_left() as i64, ascenso - glifo.bitmap_top() as i64);
            let (paso, datos) = (bitmap.pitch().unsigned_abs() as usize, bitmap.buffer());
            for y in 0..bitmap.rows() as usize {
                for x in 0..bitmap.width() as usize {
                    if datos[y * paso + x / 8] & (0x80 >> (x % 8)) != 0 {
                        pixeles.push((izq + x as i64, arriba + y as i64));
                    }
                }
            }
            // El avance sin hinting, de 16.16 a 26.6.
            pluma += (glifo.linear_hori_advance() as i64 + 512) >> 10;
        }
        Ok(Self { pixeles, largo: pluma as f64 / 64.0 })
    }
    /// La caja como `textbbox` de PIL: a lo ancho, de 0 al largo por avances (truncado), no por la
    /// tinta; a lo alto, la tinta (izq, arriba, der, abajo).
    fn caja(&self) -> (i64, i64, i64, i64) {
        let (mut arriba, mut abajo) = (i64::MAX, i64::MIN);
        for &(_, y) in &self.pixeles {
            (arriba, abajo) = (arriba.min(y), abajo.max(y + 1));
        }
        if arriba == i64::MAX { (0, 0, 0, 0) } else { (0, arriba, self.largo.floor() as i64, abajo) }
    }
    fn dibujar(&self, mapa: &mut Mapa, x0: i64, y0: i64) {
        for &(x, y) in &self.pixeles {
            mapa.pintar(x0 + x, y0 + y);
        }
    }
}

/// Barras y, debajo, la leyenda, en exactamente `ancho` × `alto` (`dibujar_codigo` de la v2).
pub fn dibujar_codigo(texto: &str, ancho: usize, alto: usize, leyenda: Option<&str>) -> Result<Mapa, String> {
    let modulos = code128(texto)?;
    let leyenda = leyenda.unwrap_or(texto);
    let biblioteca = freetype::Library::init().map_err(|e| e.to_string())?;
    let cara = biblioteca.new_memory_face(std::rc::Rc::new(FUENTE.to_vec()), 0).map_err(|e| e.to_string())?;
    let mut tamano = TAMANO_TEXTO_PX;
    let mut t = Texto::nuevo(&cara, leyenda, tamano)?;
    while tamano > 8 && t.largo > ancho as f64 {
        tamano -= 1;
        t = Texto::nuevo(&cara, leyenda, tamano)?;
    }
    let (izq, arriba, der, abajo) = t.caja();
    let alto_texto = (abajo - arriba) as usize;
    let alto_barras = (alto as i64 - alto_texto as i64 - SEPARACION_TEXTO_PX as i64).max(1);

    let mut mapa = Mapa::blanco(ancho, alto);
    // Módulos de ancho entero (mínimo 2 px): las barras del mismo grosor salen idénticas.
    let n = modulos.len();
    let entero = ancho / n;
    let paso = if entero >= 2 { entero as f64 } else { ancho as f64 / n as f64 };
    let inicio = (ancho as f64 - paso * n as f64) / 2.0;
    for (i, m) in modulos.chars().enumerate() {
        if m == '1' {
            let x0 = redondear(inicio + i as f64 * paso);
            let x1 = redondear(inicio + (i + 1) as f64 * paso);
            mapa.rectangulo(x0, 0, x1 - 1, alto_barras - 1);
        }
    }
    // Como PIL (medido): la x se trunca y su fracción no mueve las letras.
    let x_texto = (ancho as f64 - (der - izq) as f64) / 2.0 - izq as f64;
    t.dibujar(&mut mapa, x_texto.trunc() as i64, alto as i64 - alto_texto as i64 - arriba);
    Ok(mapa)
}

/// Línea punteada horizontal de 2 px de grueso (guía para recortar).
fn linea_punteada(mapa: &mut Mapa, x0: i64, x1: i64, y: i64) {
    let (trazo, hueco) = (6, 4);
    let mut x = x0;
    while x < x1 {
        mapa.rectangulo(x, y, (x + trazo - 1).min(x1), y + 1);
        x += trazo + hueco;
    }
}

/// La etiqueta en vertical: 3 piezas apiladas (None = hueco), con líneas punteadas entre ellas, y
/// girada 90° a la izquierda (`componer_vertical` de la v2). `leyendas`: el texto bajo cada código.
pub fn etiqueta_vertical(textos: &[Option<&str>], leyendas: &[(&str, &str)]) -> Result<Mapa, String> {
    let [m_arriba, m_derecho, m_abajo, m_izquierdo] = MARGENES;
    let (ancho_d, alto_d) = (ALTO_PX, ANCHO_PX);
    let (arriba_d, abajo_d, izquierda_d, derecha_d) = (m_izquierdo, m_derecho, m_abajo, m_arriba);
    let ancho_util = ancho_d - izquierda_d - derecha_d;
    let alto_util = alto_d - arriba_d - abajo_d;
    let alto_parte = (alto_util - SEPARACION_PIEZAS_PX * (PIEZAS_POR_ETIQUETA - 1)) / PIEZAS_POR_ETIQUETA;
    let mut lienzo = Mapa::blanco(ancho_d, alto_d);
    let mut hechas: Vec<(&str, Mapa)> = Vec::new();
    for (i, texto) in textos.iter().take(PIEZAS_POR_ETIQUETA).enumerate() {
        let y = arriba_d + i * (alto_parte + SEPARACION_PIEZAS_PX);
        if i > 0 && textos[i - 1].is_some() {
            linea_punteada(&mut lienzo, 0, ancho_d as i64 - 1, (y - SEPARACION_PIEZAS_PX / 2) as i64);
        }
        let Some(texto) = texto else { continue };
        if !hechas.iter().any(|(t, _)| t == texto) {
            let leyenda = leyendas.iter().find(|(c, _)| c == texto).map(|(_, l)| *l);
            hechas.push((texto, dibujar_codigo(texto, ancho_util, alto_parte, leyenda)?));
        }
        let pieza = &hechas.iter().find(|(t, _)| t == texto).expect("dibujada").1;
        lienzo.pegar(pieza, izquierda_d, y);
    }
    Ok(lienzo.girada_izquierda())
}

/// [("ABC", 2), ("XYZ", 4)] → etiquetas de 3 piezas en orden; la última con huecos (`None`).
pub fn repartir_en_etiquetas<'a>(piezas: &[(&'a str, usize)]) -> Vec<Vec<Option<&'a str>>> {
    let seguidas: Vec<&str> = piezas.iter().flat_map(|(c, n)| std::iter::repeat_n(*c, *n)).collect();
    let mut etiquetas: Vec<Vec<Option<&str>>> = seguidas.chunks(PIEZAS_POR_ETIQUETA).map(|c| c.iter().map(|x| Some(*x)).collect()).collect();
    if let Some(ultima) = etiquetas.last_mut() {
        ultima.resize(PIEZAS_POR_ETIQUETA, None);
    }
    etiquetas
}

/// Lo que se lee bajo las barras: el precio en centavos pegado al código (`leyenda_con_precio` de
/// la v2): "ABCDEF" a $100 → "10000ABCDEF". El precio va en la etiqueta sin que se note.
pub fn leyenda_con_precio(codigo: &str, precio: f64) -> String {
    format!("{}{codigo}", redondear(precio * 100.0))
}

// ---- El protocolo de la NIIMBOT (niimprint) --------------------------------------------------

/// `55 55 · tipo · largo · datos · XOR · AA AA`.
pub fn paquete(tipo: u8, datos: &[u8]) -> Vec<u8> {
    let suma = datos.iter().fold(tipo ^ datos.len() as u8, |s, b| s ^ b);
    let mut p = vec![0x55, 0x55, tipo, datos.len() as u8];
    p.extend(datos);
    p.extend([suma, 0xAA, 0xAA]);
    p
}

/// Los renglones de la imagen: 1 = negro, 0x85 con el número de renglón.
fn paquetes_imagen(mapa: &Mapa) -> Vec<Vec<u8>> {
    let bytes = mapa.ancho.div_ceil(8);
    (0..mapa.alto)
        .map(|y| {
            let mut datos = vec![(y >> 8) as u8, y as u8, 0, 0, 0, 1];
            let mut fila = vec![0u8; bytes];
            for x in 0..mapa.ancho {
                if mapa.en(x, y) {
                    fila[x / 8] |= 0x80 >> (x % 8);
                }
            }
            datos.extend(fila);
            paquete(0x85, &datos)
        })
        .collect()
}

/// Por donde habla con la impresora (el puerto serie en la app; uno falso en las pruebas).
pub trait Transporte {
    fn escribir(&mut self, datos: &[u8]) -> Result<(), String>;
    /// Lo que haya llegado (hasta 1024 bytes), esperando un poco.
    fn leer(&mut self) -> Result<Vec<u8>, String>;
    fn esperar(&mut self, tiempo: Duration) {
        std::thread::sleep(tiempo);
    }
}

/// El cliente de la v2 (`PrinterClientFixed` sobre `PrinterClient` de niimprint).
pub struct Niimbot<T: Transporte> {
    transporte: T,
    recibido: Vec<u8>,
}

impl<T: Transporte> Niimbot<T> {
    pub fn nueva(transporte: T) -> Self {
        Self { transporte, recibido: Vec::new() }
    }
    pub fn transporte(&self) -> &T {
        &self.transporte
    }
    fn enviar(&mut self, tipo: u8, datos: &[u8]) -> Result<(), String> {
        self.transporte.escribir(&paquete(tipo, datos))
    }
    /// Los paquetes completos que hayan llegado.
    fn recibir(&mut self) -> Result<Vec<(u8, Vec<u8>)>, String> {
        self.recibido.extend(self.transporte.leer()?);
        let mut paquetes = Vec::new();
        while self.recibido.len() > 4 {
            let largo = self.recibido[3] as usize + 7;
            if self.recibido.len() < largo {
                break;
            }
            let p: Vec<u8> = self.recibido.drain(..largo).collect();
            paquetes.push((p[2], p[4..4 + p[3] as usize].to_vec()));
        }
        Ok(paquetes)
    }
    /// Manda y espera la respuesta `tipo + desplazamiento` (6 intentos, como niimprint).
    fn preguntar(&mut self, tipo: u8, datos: &[u8], desplazamiento: u8) -> Result<Vec<u8>, String> {
        let respuesta = tipo.wrapping_add(desplazamiento);
        self.enviar(tipo, datos)?;
        for _ in 0..6 {
            let mut hallada = None;
            for (t, d) in self.recibir()? {
                match t {
                    219 => return Err("La etiquetadora rechazó la orden.".into()),
                    0 => return Err("La etiquetadora no entiende la orden.".into()),
                    t if t == respuesta => hallada = Some(d),
                    _ => {}
                }
            }
            if let Some(d) = hallada {
                return Ok(d);
            }
            self.transporte.esperar(Duration::from_millis(100));
        }
        Err("La etiquetadora no respondió.".into())
    }
    fn enviar_y_vaciar(&mut self, tipo: u8, datos: &[u8], espera: u64) -> Result<(), String> {
        self.enviar(tipo, datos)?;
        self.transporte.esperar(Duration::from_millis(espera));
        let _ = self.recibir();
        Ok(())
    }

    /// Imprime una etiqueta (`PrinterClientFixed.print_image`). `esperar_final`: solo en la última.
    pub fn imprimir(&mut self, mapa: &Mapa, densidad: u8, esperar_final: bool) -> Result<(), String> {
        self.enviar_y_vaciar(0x54, &[1], 50)?;
        self.preguntar(0x21, &[densidad], 16)?;
        self.preguntar(0x23, &[1], 16)?;
        self.enviar_y_vaciar(0x01, &[0, 1, 0, 0, 0, 0, 0], 100)?;
        self.preguntar(0x03, &[1], 1)?;
        let (alto, ancho) = (mapa.alto as u16, mapa.ancho as u16);
        self.enviar_y_vaciar(0x13, &[(alto >> 8) as u8, alto as u8, (ancho >> 8) as u8, ancho as u8, 0, 1], 100)?;
        for p in paquetes_imagen(mapa) {
            self.transporte.escribir(&p)?;
        }
        self.preguntar(0xE3, &[1], 1)?;
        if esperar_final {
            // Hasta que termine (progreso 0 y 0), máximo 15 s; luego cerrar la impresión.
            for _ in 0..150 {
                if let Ok(d) = self.preguntar(0xA3, &[1], 16) {
                    if d.len() >= 4 && d[2] == 0 && d[3] == 0 {
                        break;
                    }
                }
                self.transporte.esperar(Duration::from_millis(100));
            }
            for _ in 0..100 {
                if self.preguntar(0xF3, &[1], 1)?.first().is_some_and(|b| *b != 0) {
                    return Ok(());
                }
                self.transporte.esperar(Duration::from_millis(100));
            }
            return Err("La etiquetadora no terminó la impresión.".into());
        }
        Ok(())
    }
}

#[cfg(test)]
mod pruebas {
    use super::*;
    use serde_json::Value;

    fn casos() -> Value {
        serde_json::from_str(include_str!("../pruebas_v2/etiquetas_v2.json")).unwrap()
    }
    fn mapa_de(v: &Value) -> Mapa {
        let renglones: Vec<&str> = v["renglones"].as_array().unwrap().iter().map(|r| r.as_str().unwrap()).collect();
        Mapa { ancho: renglones[0].len(), alto: renglones.len(), negro: renglones.iter().flat_map(|r| r.chars().map(|c| c == '1')).collect() }
    }
    /// Píxeles distintos entre dos mapas del mismo tamaño.
    fn distintos(a: &Mapa, b: &Mapa) -> usize {
        a.negro.iter().zip(&b.negro).filter(|(x, y)| x != y).count()
    }

    #[test]
    fn code128_identico_a_la_v2() {
        for (codigo, modulos) in casos()["modulos"].as_object().unwrap() {
            assert_eq!(code128(codigo).unwrap(), modulos.as_str().unwrap(), "{codigo}");
        }
        assert!(code128("ä").is_err());
    }

    #[test]
    fn la_pieza_es_identica_a_la_de_la_v2() {
        let c = casos();
        let v2 = mapa_de(&c["pieza"]);
        let v3 = dibujar_codigo("A1B2C3", 200, 98, Some("15000A1B2C3")).unwrap();
        assert_eq!((v3.ancho, v3.alto), (v2.ancho, v2.alto));
        assert_eq!(distintos(&v2, &v3), 0, "píxeles distintos (barras y texto)");
    }

    #[test]
    fn la_etiqueta_vertical_es_identica_a_la_de_la_v2() {
        let c = casos();
        let v2 = mapa_de(&c["etiqueta"]);
        let leyendas: Vec<(&str, &str)> = c["etiqueta"]["leyendas"].as_object().unwrap().iter().map(|(k, v)| (k.as_str(), v.as_str().unwrap())).collect();
        let v3 = etiqueta_vertical(&[Some("A1B2C3"), None, Some("123456")], &leyendas).unwrap();
        assert_eq!((v3.ancho, v3.alto), (ANCHO_PX, ALTO_PX));
        assert_eq!(distintos(&v2, &v3), 0, "píxeles distintos");
    }

    /// Una NIIMBOT falsa que responde "OK" (como la del generador de la v2).
    struct Falsa {
        enviado: Vec<u8>,
        respuestas: Vec<u8>,
    }
    impl Transporte for Falsa {
        fn escribir(&mut self, datos: &[u8]) -> Result<(), String> {
            self.enviado.extend(datos);
            let tipo = datos[2];
            match tipo {
                0x85 => {}
                0xA3 => self.respuestas.extend(paquete(tipo + 16, &[0, 1, 0, 0])),
                0x21 | 0x23 => self.respuestas.extend(paquete(tipo + 16, &[1])),
                _ => self.respuestas.extend(paquete(tipo.wrapping_add(1), &[1])),
            }
            Ok(())
        }
        fn leer(&mut self) -> Result<Vec<u8>, String> {
            let n = self.respuestas.len().min(1024);
            Ok(self.respuestas.drain(..n).collect())
        }
        fn esperar(&mut self, _: Duration) {}
    }

    #[test]
    fn los_paquetes_son_identicos_a_los_de_la_v2() {
        let c = casos();
        let v2 = mapa_de(&c["etiqueta"]);
        let mut n = Niimbot::nueva(Falsa { enviado: Vec::new(), respuestas: Vec::new() });
        n.imprimir(&v2, 1, true).unwrap();
        let hex: String = n.transporte().enviado.iter().map(|b| format!("{b:02x}")).collect();
        assert_eq!(hex, c["paquetes"]["hex"].as_str().unwrap());
    }

    #[test]
    fn repartir_y_leyenda_como_la_v2() {
        let e = repartir_en_etiquetas(&[("ABC", 2), ("XYZ", 4)]);
        assert_eq!(e, vec![vec![Some("ABC"), Some("ABC"), Some("XYZ")], vec![Some("XYZ"), Some("XYZ"), Some("XYZ")]]);
        assert_eq!(repartir_en_etiquetas(&[("A", 1)]), vec![vec![Some("A"), None, None]]);
        assert_eq!(leyenda_con_precio("ABCDEF", 100.0), "10000ABCDEF");
        assert_eq!(leyenda_con_precio("X", 99.5), "9950X");
    }
}

