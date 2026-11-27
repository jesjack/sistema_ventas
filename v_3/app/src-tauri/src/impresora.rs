//! La impresora de tickets (y el cajón, que se abre a través de ella), como la v2
//! (`v_2/hardware/ticket_printer.py`). Los bytes los arma `nucleo::ticket`; aquí se escriben.
//!
//! SIMULADA POR DEFECTO mientras la v2 sea la oficial en la misma PC: si la v3 imprimiera de verdad
//! durante la prueba en paralelo, cada venta repetida sacaría un ticket de más y abriría el cajón.
//! Simulada, guarda el último ticket en `ultimo_ticket.bin` (junto a la base) para revisarlo. Se
//! enciende desde Desarrollador o con `CAJA_HARDWARE=1`.

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Mutex, mpsc};
use std::time::Duration;

use nucleo::ticket::{Imagen, Tienda};
use serde::Serialize;

/// Una impresora atascada dejaba la escritura esperando para siempre (v2, 2026-09-23): se deja de
/// esperar a los 5 s y se avisa.
const LIMITE: Duration = Duration::from_secs(5);
/// La etiquetadora NIIMBOT también aparece como impresora (/dev/usb/lp*): no es la de tickets.
const NO_SON_DE_TICKETS: &[&str] = &["3513"];

#[derive(Default)]
pub struct Impresora {
    real: AtomicBool,
    estado: Mutex<String>,
}

#[derive(Serialize)]
pub struct EstadoImpresora {
    real: bool,
    estado: String,
}

impl Impresora {
    pub fn nueva() -> Self {
        let i = Self::default();
        if std::env::var("CAJA_HARDWARE").is_ok_and(|v| v == "1") {
            i.real.store(true, Ordering::Relaxed);
        }
        i.poner_estado(if i.es_real() { "real (aún sin imprimir)" } else { "simulada: los tickets se guardan en ultimo_ticket.bin" });
        i
    }
    pub fn es_real(&self) -> bool {
        self.real.load(Ordering::Relaxed)
    }
    pub fn activar(&self, real: bool) {
        self.real.store(real, Ordering::Relaxed);
        self.poner_estado(if real { "real" } else { "simulada: los tickets se guardan en ultimo_ticket.bin" });
    }
    pub fn estado(&self) -> EstadoImpresora {
        EstadoImpresora { real: self.es_real(), estado: self.estado.lock().map(|e| e.clone()).unwrap_or_default() }
    }
    fn poner_estado(&self, texto: impl Into<String>) {
        if let Ok(mut e) = self.estado.lock() {
            *e = texto.into();
        }
    }

    /// Manda los bytes. Simulada: los guarda en `carpeta/ultimo_ticket.bin`. Real: busca la
    /// impresora y escribe con límite de tiempo. Devuelve dónde quedó (para el aviso).
    pub fn enviar(&self, bytes: &[u8], carpeta: &Path) -> Result<String, String> {
        if !self.es_real() {
            let ruta = carpeta.join("ultimo_ticket.bin");
            std::fs::write(&ruta, bytes).map_err(|e| format!("No se pudo guardar el ticket simulado: {e}"))?;
            return Ok("simulada".into());
        }
        let dispositivo = buscar_dispositivo().ok_or("No se encontró la impresora de tickets.")?;
        let resultado = escribir_con_limite(&dispositivo, bytes.to_vec());
        match &resultado {
            Ok(()) => self.poner_estado(format!("real: último envío correcto a {}", dispositivo.display())),
            Err(e) => self.poner_estado(format!("real: falló el último envío ({e})")),
        }
        resultado.map(|()| dispositivo.display().to_string())
    }
}

/// Escribe en otro hilo y deja de esperar a los `LIMITE` (el hilo queda abandonado si se atascó).
fn escribir_con_limite(dispositivo: &Path, bytes: Vec<u8>) -> Result<(), String> {
    let (tx, rx) = mpsc::channel();
    let ruta = dispositivo.to_path_buf();
    std::thread::spawn(move || {
        use std::io::Write;
        let r = std::fs::OpenOptions::new().write(true).open(&ruta).and_then(|mut f| {
            f.write_all(&bytes)?;
            f.flush()
        });
        let _ = tx.send(r.map_err(|e| e.to_string()));
    });
    match rx.recv_timeout(LIMITE) {
        Ok(r) => r.map_err(|e| format!("No se pudo imprimir en {}: {e}", dispositivo.display())),
        Err(_) => Err(format!("La impresora no respondió en {} s ({}).", LIMITE.as_secs(), dispositivo.display())),
    }
}

/// El fabricante USB de un /dev (por sysfs), para descartar la etiquetadora.
fn fabricante(dispositivo: &Path) -> Option<(String, String)> {
    let nombre = dispositivo.file_name()?.to_str()?;
    let clase = ["usbmisc", "tty", "usb", "printer"].iter().map(|s| PathBuf::from(format!("/sys/class/{s}/{nombre}"))).find(|p| p.exists())?;
    let mut nodo = std::fs::canonicalize(clase.join("device")).ok()?;
    for _ in 0..8 {
        if nodo.join("idVendor").is_file() {
            let leer = |a: &str| std::fs::read_to_string(nodo.join(a)).map(|s| s.trim().to_lowercase()).unwrap_or_default();
            return Some((leer("idVendor"), format!("{} {}", leer("manufacturer"), leer("product"))));
        }
        nodo = nodo.parent()?.to_path_buf();
    }
    None
}

fn no_es_de_tickets(dispositivo: &Path) -> bool {
    fabricante(dispositivo).is_some_and(|(vendor, nombre)| NO_SON_DE_TICKETS.contains(&vendor.as_str()) || nombre.contains("niimbot"))
}

/// Como `find_printer_device` de la v2: /dev/usb/lp*, puertos serie y /dev/lp*, sin la NIIMBOT
/// (si solo queda ella, se usa como último recurso, como la v2).
fn buscar_dispositivo() -> Option<PathBuf> {
    let mut candidatos: Vec<PathBuf> = Vec::new();
    for patron in ["/dev/usb", "/dev"] {
        if let Ok(entradas) = std::fs::read_dir(patron) {
            let mut v: Vec<PathBuf> = entradas
                .flatten()
                .map(|e| e.path())
                .filter(|p| {
                    let n = p.file_name().and_then(|n| n.to_str()).unwrap_or("");
                    if patron == "/dev/usb" { n.starts_with("lp") } else { n.starts_with("ttyUSB") || n.starts_with("ttyACM") || n.starts_with("lp") }
                })
                .collect();
            v.sort();
            candidatos.extend(v);
        }
    }
    let (buenos, otros): (Vec<PathBuf>, Vec<PathBuf>) = candidatos.into_iter().partition(|p| !no_es_de_tickets(p));
    buenos.into_iter().next().or_else(|| otros.into_iter().next())
}

/// Los datos de la tienda para el ticket: `tienda.json` junto a la base (lo crea
/// `scripts/configurar_tienda.py` desde la v2; está fuera de git). Sin él, un ticket sin encabezado,
/// logo ni QR.
pub fn tienda(carpeta: &Path) -> Result<Tienda, String> {
    #[derive(serde::Deserialize)]
    struct Qr {
        ancho_bytes: u16,
        alto: u16,
        hex: String,
    }
    #[derive(serde::Deserialize)]
    struct Archivo {
        nombre: String,
        encabezado: Vec<String>,
        logo_hex: Option<String>,
        qr: Option<Qr>,
    }
    let ruta = carpeta.join("tienda.json");
    let texto = std::fs::read_to_string(&ruta).map_err(|_| format!("Falta {} (scripts/configurar_tienda.py).", ruta.display()))?;
    let a: Archivo = serde_json::from_str(&texto).map_err(|e| format!("{} no es válido: {e}", ruta.display()))?;
    let hex = |s: &str| -> Result<Vec<u8>, String> {
        (0..s.len()).step_by(2).map(|i| u8::from_str_radix(s.get(i..i + 2).unwrap_or("zz"), 16).map_err(|e| e.to_string())).collect()
    };
    Ok(Tienda {
        nombre: a.nombre,
        encabezado: a.encabezado,
        logo: a.logo_hex.as_deref().map(hex).transpose()?,
        qr: a.qr.map(|q| hex(&q.hex).map(|datos| Imagen { ancho_bytes: q.ancho_bytes, alto: q.alto, datos })).transpose()?,
    })
}
