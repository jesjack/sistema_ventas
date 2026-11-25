//! Lectura DIRECTA del escáner de códigos de barras (Linux, evdev), aunque otra app tenga el foco.
//!
//! El escáner es un teclado USB aparte. Con permiso de lectura sobre su dispositivo (regla de udev
//! con `TAG+="uaccess"`: lo da systemd a quien tenga la sesión frente a la PC, sin grupos), la caja
//! lo abre y lo toma EN EXCLUSIVA (EVIOCGRAB): sus teclas ya no llegan a la app que está al frente.
//! Cada código (hasta Intro) se manda a la vista como el evento `escaneo` y la ventana pide pasar
//! al frente.
//!
//! Mientras la v2 siga siendo la oficial en la misma PC, esto va APAGADO por defecto (tomarlo en
//! exclusiva dejaría a la v2 sin escáner); se enciende desde Desarrollador o con
//! `CAJA_ESCANER_DIRECTO=1`. Sin permiso o sin escáner, la caja sigue con la detección por ritmo de
//! tecleo (`escaner.ts`), que solo funciona con la caja al frente.

use std::os::fd::AsRawFd;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use evdev::{Device, EventSummary, KeyCode};
use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager};

/// El escáner de la tienda: Honeywell (USB `0c2e:0200`). Otros modelos: fase 6 (detectarlo solo).
const ESCANERES: &[(u16, u16)] = &[(0x0c2e, 0x0200)];

#[derive(Default)]
pub struct Escaner {
    activo: AtomicBool,
    estado: Mutex<String>,
}

#[derive(Serialize)]
pub struct EstadoEscaner {
    activo: bool,
    estado: String,
}

impl Escaner {
    pub fn estado(&self) -> EstadoEscaner {
        EstadoEscaner {
            activo: self.activo.load(Ordering::Relaxed),
            estado: self.estado.lock().map(|e| e.clone()).unwrap_or_default(),
        }
    }

    pub fn activar(&self, activo: bool) {
        self.activo.store(activo, Ordering::Relaxed);
    }

    fn poner_estado(&self, texto: impl Into<String>) {
        if let Ok(mut e) = self.estado.lock() {
            *e = texto.into();
        }
    }
}

/// Arranca el hilo que vigila el escáner. Mientras esté apagado no abre nada; encendido, lo busca
/// (cada 3 s si no está), lo toma en exclusiva y lee códigos. Al apagarlo, lo suelta.
pub fn iniciar(app: AppHandle, escaner: Arc<Escaner>) {
    if std::env::var("CAJA_ESCANER_DIRECTO").is_ok_and(|v| v == "1") {
        escaner.activar(true);
    }
    escaner.poner_estado("apagado");
    std::thread::spawn(move || loop {
        if !escaner.activo.load(Ordering::Relaxed) {
            escaner.poner_estado("apagado (los escaneos llegan como teclas a la app que está al frente)");
            std::thread::sleep(Duration::from_millis(500));
            continue;
        }
        match abrir() {
            Ok(mut dispositivo) => {
                let nombre = dispositivo.name().unwrap_or("escáner").to_string();
                escaner.poner_estado(format!("leyendo en exclusiva: {nombre}"));
                if let Err(e) = leer(&app, &escaner, &mut dispositivo) {
                    escaner.poner_estado(format!("se perdió el escáner ({e}); reintentando"));
                }
                let _ = dispositivo.ungrab();
            }
            Err(e) => {
                escaner.poner_estado(e);
                std::thread::sleep(Duration::from_secs(3));
            }
        }
    });
}

fn abrir() -> Result<Device, String> {
    let mut sin_permiso = None;
    for (ruta, dispositivo) in evdev::enumerate() {
        let id = dispositivo.input_id();
        if !ESCANERES.contains(&(id.vendor(), id.product())) {
            continue;
        }
        // `enumerate` ya lo abrió: si lo listó, se puede leer. Falta tomarlo en exclusiva.
        let mut dispositivo = dispositivo;
        match dispositivo.grab() {
            Ok(()) => return Ok(dispositivo),
            Err(e) => sin_permiso = Some(format!("no se pudo tomar {} en exclusiva: {e}", ruta.display())),
        }
    }
    Err(sin_permiso.unwrap_or_else(|| {
        "no se encontró el escáner o no hay permiso para leerlo (falta la regla de udev con uaccess); reintentando".into()
    }))
}

/// Lee hasta que lo apaguen o se desconecte. Espera eventos con `poll` (medio segundo) para notar
/// cuando lo apagan aunque nadie escanee.
fn leer(app: &AppHandle, escaner: &Escaner, dispositivo: &mut Device) -> Result<(), String> {
    let fd = dispositivo.as_raw_fd();
    let (mut codigo, mut mayus) = (String::new(), false);
    while escaner.activo.load(Ordering::Relaxed) {
        let mut pfd = libc::pollfd { fd, events: libc::POLLIN, revents: 0 };
        // SAFETY: un solo pollfd válido mientras `dispositivo` vive.
        let listo = unsafe { libc::poll(&mut pfd, 1, 500) };
        if listo < 0 {
            return Err(std::io::Error::last_os_error().to_string());
        }
        if listo == 0 {
            continue;
        }
        if pfd.revents & (libc::POLLERR | libc::POLLHUP | libc::POLLNVAL) != 0 {
            return Err("desconectado".into());
        }
        for evento in dispositivo.fetch_events().map_err(|e| e.to_string())? {
            let EventSummary::Key(_, tecla, valor) = evento.destructure() else { continue };
            if tecla == KeyCode::KEY_LEFTSHIFT || tecla == KeyCode::KEY_RIGHTSHIFT {
                mayus = valor != 0;
                continue;
            }
            if valor != 1 {
                continue; // solo al presionar (no al soltar ni al repetir)
            }
            if tecla == KeyCode::KEY_ENTER || tecla == KeyCode::KEY_KPENTER {
                if !codigo.is_empty() {
                    entregar(app, std::mem::take(&mut codigo));
                }
            } else if let Some(c) = caracter(tecla, mayus) {
                codigo.push(c);
            }
        }
    }
    Ok(())
}

/// Manda el código a la vista y pide pasar al frente (en Wayland el sistema puede negarlo y solo
/// avisar que la caja está lista; para eso también se pide atención).
fn entregar(app: &AppHandle, codigo: String) {
    let _ = app.emit("escaneo", &codigo);
    if let Some(ventana) = app.get_webview_window("main") {
        let _ = ventana.unminimize();
        let _ = ventana.show();
        let _ = ventana.set_focus();
        if !ventana.is_focused().unwrap_or(true) {
            let _ = ventana.request_user_attention(Some(tauri::UserAttentionType::Critical));
        }
    }
}

/// Tecla → carácter con la distribución que usa el escáner (EE. UU.: la de fábrica). Los códigos
/// de la tienda son números; las letras y símbolos comunes, por si acaso.
fn caracter(tecla: KeyCode, mayus: bool) -> Option<char> {
    const NUMEROS: [(KeyCode, char, char); 10] = [
        (KeyCode::KEY_1, '1', '!'), (KeyCode::KEY_2, '2', '@'), (KeyCode::KEY_3, '3', '#'), (KeyCode::KEY_4, '4', '$'),
        (KeyCode::KEY_5, '5', '%'), (KeyCode::KEY_6, '6', '^'), (KeyCode::KEY_7, '7', '&'), (KeyCode::KEY_8, '8', '*'),
        (KeyCode::KEY_9, '9', '('), (KeyCode::KEY_0, '0', ')'),
    ];
    const LETRAS: [(KeyCode, char); 26] = [
        (KeyCode::KEY_A, 'a'), (KeyCode::KEY_B, 'b'), (KeyCode::KEY_C, 'c'), (KeyCode::KEY_D, 'd'), (KeyCode::KEY_E, 'e'),
        (KeyCode::KEY_F, 'f'), (KeyCode::KEY_G, 'g'), (KeyCode::KEY_H, 'h'), (KeyCode::KEY_I, 'i'), (KeyCode::KEY_J, 'j'),
        (KeyCode::KEY_K, 'k'), (KeyCode::KEY_L, 'l'), (KeyCode::KEY_M, 'm'), (KeyCode::KEY_N, 'n'), (KeyCode::KEY_O, 'o'),
        (KeyCode::KEY_P, 'p'), (KeyCode::KEY_Q, 'q'), (KeyCode::KEY_R, 'r'), (KeyCode::KEY_S, 's'), (KeyCode::KEY_T, 't'),
        (KeyCode::KEY_U, 'u'), (KeyCode::KEY_V, 'v'), (KeyCode::KEY_W, 'w'), (KeyCode::KEY_X, 'x'), (KeyCode::KEY_Y, 'y'),
        (KeyCode::KEY_Z, 'z'),
    ];
    const SIMBOLOS: [(KeyCode, char, char); 6] = [
        (KeyCode::KEY_MINUS, '-', '_'), (KeyCode::KEY_DOT, '.', '>'), (KeyCode::KEY_SLASH, '/', '?'),
        (KeyCode::KEY_SPACE, ' ', ' '), (KeyCode::KEY_EQUAL, '=', '+'), (KeyCode::KEY_COMMA, ',', '<'),
    ];
    if let Some(&(_, n, s)) = NUMEROS.iter().find(|(k, ..)| *k == tecla) {
        return Some(if mayus { s } else { n });
    }
    if let Some(&(_, l)) = LETRAS.iter().find(|(k, _)| *k == tecla) {
        return Some(if mayus { l.to_ascii_uppercase() } else { l });
    }
    SIMBOLOS.iter().find(|(k, ..)| *k == tecla).map(|&(_, n, s)| if mayus { s } else { n })
}
