//! Turno de caja, permisos, código de autorización y aperturas del cajón (D8, D20, D21, D23 en
//! `v_3/docs/mapa_v2.md`; tablas en `esquema/v2.sql`).
//!
//! - **Turno (D8):** una sola caja activa por equipo. `tomar_turno` suma 1 al número vigente; cada
//!   caja guarda el número que tomó y comprueba con `turno_vigente` (cada ~3 s y antes de cada
//!   acción con efecto) que sigue siendo el suyo. Si no, otra caja tomó el turno: no hace nada más
//!   y se cierra (D23: entera, cámaras incluidas).
//! - **Permisos (D21):** por usuario, no por nombre en el código.
//! - **Apertura del cajón:** `como_abrir` decide (permiso, ventana diaria o código) y
//!   `registrar_apertura` deja constancia SOLO después de que el cajón se abrió de verdad (como la
//!   v2: un fallo de la impresora no debe dejar un evento que diga que se abrió).
//! - **Código (D20/D21):** uno solo, como hash con sal, de un solo uso: al usarse queda bloqueado
//!   hasta que alguien con "abrir caja sin límite" ponga uno nuevo.

use getrandom::fill;
use rusqlite::{OptionalExtension, params};
use serde::Serialize;
use sha2::{Digest, Sha256};

use crate::base::{Base, ErrorBase};
use crate::ventas::Momento;

/// Evento que deja cada apertura en VENTAS REALIZADAS (el mismo texto que la v2).
pub const EVENTO_APERTURA: &str = "APERTURA DE CAJA";

/// Permisos de D21.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum Permiso {
    /// Menú de administración: botones, configuración, permisos.
    Desarrollador,
    /// "Abrir caja" siempre, sin código; pone el código de autorización.
    AbrirCajaSinLimite,
    /// "Abrir caja" una vez al día, antes de la primera venta.
    Empleada,
}

impl Permiso {
    pub const TODOS: [Permiso; 3] = [Permiso::Desarrollador, Permiso::AbrirCajaSinLimite, Permiso::Empleada];

    pub fn clave(self) -> &'static str {
        match self {
            Permiso::Desarrollador => "desarrollador",
            Permiso::AbrirCajaSinLimite => "abrir_caja_sin_limite",
            Permiso::Empleada => "empleada",
        }
    }

    fn de_clave(clave: &str) -> Option<Self> {
        Self::TODOS.into_iter().find(|p| p.clave() == clave)
    }
}

/// Cómo se autoriza (o se autorizó) una apertura del cajón.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum Autorizacion {
    /// El usuario tiene "abrir caja sin límite".
    Permiso,
    /// La empleada, una vez al día antes de la primera venta (para contar el cambio).
    VentanaDiaria,
    /// Con el código de un solo uso.
    Codigo,
    /// Al cobrar una venta (D23: también entra al registro).
    Venta,
}

impl Autorizacion {
    pub fn clave(self) -> &'static str {
        match self {
            Autorizacion::Permiso => "permiso",
            Autorizacion::VentanaDiaria => "ventana_diaria",
            Autorizacion::Codigo => "codigo",
            Autorizacion::Venta => "venta",
        }
    }

    fn detalle(self) -> &'static str {
        match self {
            Autorizacion::Permiso => "Se abrió la caja (permiso sin límite).",
            Autorizacion::VentanaDiaria => "Se abrió la caja para contar el cambio (una vez al día, antes de la primera venta).",
            Autorizacion::Codigo => "Se abrió la caja con el código autorizado.",
            Autorizacion::Venta => "Se abrió la caja al cobrar una venta.",
        }
    }
}

/// El estado del código de autorización.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub enum EstadoCodigo {
    /// Nadie ha puesto un código todavía.
    SinCodigo,
    /// Hay un código y no se ha usado.
    Disponible,
    /// Ya se usó: está bloqueado hasta que pongan uno nuevo. Quién y cuándo, para mostrarlo.
    Usado { usado_en: String, usado_sesion_id: Option<i64> },
}

#[derive(Debug, thiserror::Error)]
pub enum ErrorCaja {
    #[error("El código debe tener al menos {0} caracteres.")]
    CodigoCorto(usize),
    #[error("Solo alguien con permiso para abrir la caja sin límite puede poner el código.")]
    SinPermisoParaElCodigo,
    #[error("No hay código de autorización; pide a quien tenga permiso que abra la caja.")]
    SinCodigo,
    #[error("Código usado; pide a quien tenga permiso que abra la caja o ponga uno nuevo.")]
    CodigoUsado,
    #[error("El código no es correcto.")]
    CodigoIncorrecto,
    #[error("No se pudo generar la sal del código: {0}")]
    Aleatorio(String),
    #[error(transparent)]
    Base(#[from] ErrorBase),
}

impl From<rusqlite::Error> for ErrorCaja {
    fn from(e: rusqlite::Error) -> Self {
        Self::Base(ErrorBase::from(e))
    }
}

/// Largo mínimo del código de autorización.
pub const LARGO_MINIMO_CODIGO: usize = 4;

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn hash_codigo(sal: &str, codigo: &str) -> String {
    let mut h = Sha256::new();
    h.update(sal.as_bytes());
    h.update(codigo.trim().as_bytes());
    hex(&h.finalize())
}

/// Compara sin cortar en el primer carácter distinto (no deja adivinar por el tiempo).
fn iguales(a: &str, b: &str) -> bool {
    a.len() == b.len() && a.bytes().zip(b.bytes()).fold(0u8, |d, (x, y)| d | (x ^ y)) == 0
}

impl Base {
    // ---- Turno (D8) -------------------------------------------------------------------------

    /// Toma el turno para esta sesión. Devuelve el número tomado; la caja que tenía el anterior
    /// deja de ser la vigente.
    pub fn tomar_turno(&mut self, sesion_id: Option<i64>, momento: &Momento) -> Result<i64, ErrorBase> {
        let tx = self.con.transaction()?;
        tx.execute(
            "UPDATE turno_caja SET numero = numero + 1, sesion_id = ?1, desde = ?2 WHERE id = 1",
            params![sesion_id, format!("{} {}", momento.fecha, momento.hora)],
        )?;
        let numero = tx.query_row("SELECT numero FROM turno_caja WHERE id = 1", [], |f| f.get(0))?;
        tx.commit()?;
        Ok(numero)
    }

    /// ¿Sigue siendo `numero` el turno vigente?
    pub fn turno_vigente(&self, numero: i64) -> Result<bool, ErrorBase> {
        let vigente: i64 = self.con.query_row("SELECT numero FROM turno_caja WHERE id = 1", [], |f| f.get(0))?;
        Ok(vigente == numero)
    }

    // ---- Permisos (D21) ---------------------------------------------------------------------

    pub fn permisos(&self, usuario_id: i64) -> Result<Vec<Permiso>, ErrorBase> {
        let mut consulta = self.con.prepare_cached("SELECT permiso FROM permisos_usuario WHERE usuario_id = ?1 ORDER BY permiso")?;
        let claves: Vec<String> = consulta.query_map(params![usuario_id], |f| f.get(0))?.collect::<Result<_, _>>()?;
        Ok(claves.iter().filter_map(|c| Permiso::de_clave(c)).collect())
    }

    pub fn tiene_permiso(&self, usuario_id: i64, permiso: Permiso) -> Result<bool, ErrorBase> {
        Ok(self.permisos(usuario_id)?.contains(&permiso))
    }

    pub fn otorgar_permiso(&mut self, usuario_id: i64, permiso: Permiso) -> Result<(), ErrorBase> {
        self.con.execute("INSERT OR IGNORE INTO permisos_usuario (usuario_id, permiso) VALUES (?1, ?2)", params![usuario_id, permiso.clave()])?;
        Ok(())
    }

    pub fn quitar_permiso(&mut self, usuario_id: i64, permiso: Permiso) -> Result<(), ErrorBase> {
        self.con.execute("DELETE FROM permisos_usuario WHERE usuario_id = ?1 AND permiso = ?2", params![usuario_id, permiso.clave()])?;
        Ok(())
    }

    // ---- Apertura del cajón (D21, D23) ------------------------------------------------------

    /// Cómo puede abrir el cajón este usuario ahora (botón "Abrir caja", o Intro con el carrito
    /// vacío, que sigue las mismas reglas por D23):
    /// - con "abrir caja sin límite": `Permiso`;
    /// - empleada, si hoy todavía no hay ventas ni se usó la ventana diaria: `VentanaDiaria`;
    /// - en cualquier otro caso (también sin ningún permiso de caja, D23): `Codigo`.
    pub fn como_abrir(&self, usuario_id: i64, hoy: &str) -> Result<Autorizacion, ErrorBase> {
        let permisos = self.permisos(usuario_id)?;
        if permisos.contains(&Permiso::AbrirCajaSinLimite) {
            return Ok(Autorizacion::Permiso);
        }
        if permisos.contains(&Permiso::Empleada) {
            let ventas: i64 = self.con.query_row("SELECT count(*) FROM ventas WHERE fecha = ?1", params![hoy], |f| f.get(0))?;
            let ventana_usada: i64 = self.con.query_row(
                "SELECT count(*) FROM aperturas_caja WHERE fecha = ?1 AND autorizacion = 'ventana_diaria'",
                params![hoy],
                |f| f.get(0),
            )?;
            if ventas == 0 && ventana_usada == 0 {
                return Ok(Autorizacion::VentanaDiaria);
            }
        }
        Ok(Autorizacion::Codigo)
    }

    /// Deja constancia de una apertura que YA ocurrió: un evento "APERTURA DE CAJA" en el historial
    /// (lo que se ve en VENTAS REALIZADAS, como en la v2) y su fila en `aperturas_caja` con cómo se
    /// autorizó. Nunca guarda el código. Devuelve el id de la apertura.
    pub fn registrar_apertura(
        &mut self,
        autorizacion: Autorizacion,
        venta_id: Option<i64>,
        momento: &Momento,
        sesion_id: Option<i64>,
    ) -> Result<i64, ErrorBase> {
        let tx = self.con.transaction()?;
        tx.execute(
            "INSERT INTO eventos_especiales (fecha, hora, evento, detalle, sesion_id) VALUES (?1, ?2, ?3, ?4, ?5)",
            params![momento.fecha, momento.hora, EVENTO_APERTURA, autorizacion.detalle(), sesion_id],
        )?;
        let evento_id = tx.last_insert_rowid();
        tx.execute(
            "INSERT INTO aperturas_caja (fecha, hora, sesion_id, autorizacion, venta_id, evento_id) VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
            params![momento.fecha, momento.hora, sesion_id, autorizacion.clave(), venta_id, evento_id],
        )?;
        let apertura_id = tx.last_insert_rowid();
        tx.commit()?;
        Ok(apertura_id)
    }

    // ---- Código de autorización (D20, D21) --------------------------------------------------

    pub fn estado_codigo(&self) -> Result<EstadoCodigo, ErrorBase> {
        let fila: Option<(Option<String>, Option<i64>)> =
            self.con.query_row("SELECT usado_en, usado_sesion_id FROM codigo_caja WHERE id = 1", [], |f| Ok((f.get(0)?, f.get(1)?))).optional()?;
        Ok(match fila {
            None => EstadoCodigo::SinCodigo,
            Some((None, _)) => EstadoCodigo::Disponible,
            Some((Some(usado_en), usado_sesion_id)) => EstadoCodigo::Usado { usado_en, usado_sesion_id },
        })
    }

    /// Pone (o reemplaza) el código. Solo un usuario con "abrir caja sin límite". Se guarda como
    /// hash con una sal nueva; queda disponible para un uso.
    pub fn poner_codigo(&mut self, usuario_id: i64, codigo: &str, momento: &Momento, sesion_id: Option<i64>) -> Result<(), ErrorCaja> {
        if !self.tiene_permiso(usuario_id, Permiso::AbrirCajaSinLimite)? {
            return Err(ErrorCaja::SinPermisoParaElCodigo);
        }
        let codigo = codigo.trim();
        if codigo.chars().count() < LARGO_MINIMO_CODIGO {
            return Err(ErrorCaja::CodigoCorto(LARGO_MINIMO_CODIGO));
        }
        let mut bytes = [0u8; 16];
        fill(&mut bytes).map_err(|e| ErrorCaja::Aleatorio(e.to_string()))?;
        let sal = hex(&bytes);
        self.con.execute(
            "INSERT INTO codigo_caja (id, hash, sal, creado_en, creado_sesion_id, usado_en, usado_sesion_id)
             VALUES (1, ?1, ?2, ?3, ?4, NULL, NULL)
             ON CONFLICT (id) DO UPDATE SET hash = excluded.hash, sal = excluded.sal, creado_en = excluded.creado_en,
                 creado_sesion_id = excluded.creado_sesion_id, usado_en = NULL, usado_sesion_id = NULL",
            params![hash_codigo(&sal, codigo), sal, format!("{} {}", momento.fecha, momento.hora), sesion_id],
        )?;
        Ok(())
    }

    /// Comprueba el código y, si es correcto, lo gasta (queda bloqueado). Un código incorrecto no lo
    /// gasta. Después, el cajón se abre y se llama a `registrar_apertura(Autorizacion::Codigo, …)`.
    pub fn usar_codigo(&mut self, codigo: &str, momento: &Momento, sesion_id: Option<i64>) -> Result<(), ErrorCaja> {
        let fila: Option<(String, String, Option<String>)> =
            self.con.query_row("SELECT hash, sal, usado_en FROM codigo_caja WHERE id = 1", [], |f| Ok((f.get(0)?, f.get(1)?, f.get(2)?))).optional()?;
        let Some((hash, sal, usado_en)) = fila else { return Err(ErrorCaja::SinCodigo) };
        if usado_en.is_some() {
            return Err(ErrorCaja::CodigoUsado);
        }
        if !iguales(&hash_codigo(&sal, codigo), &hash) {
            return Err(ErrorCaja::CodigoIncorrecto);
        }
        // Gastarlo solo si nadie lo gastó entre la lectura y ahora.
        let cambios = self.con.execute(
            "UPDATE codigo_caja SET usado_en = ?1, usado_sesion_id = ?2 WHERE id = 1 AND usado_en IS NULL",
            params![format!("{} {}", momento.fecha, momento.hora), sesion_id],
        )?;
        if cambios == 0 { Err(ErrorCaja::CodigoUsado) } else { Ok(()) }
    }
}

#[cfg(test)]
mod pruebas {
    use super::*;

    fn base_con_usuarios() -> (Base, i64, i64, i64) {
        let mut base = Base::en_memoria_v3().unwrap();
        let alta = |b: &mut Base, n: &str| {
            b.con.execute("INSERT INTO usuarios_sistema (nombre_usuario, sistema_operativo) VALUES (?1, 'Linux')", params![n]).unwrap();
            b.con.last_insert_rowid()
        };
        let duena = alta(&mut base, "nancy");
        let empleada = alta(&mut base, "emilymaya");
        let otro = alta(&mut base, "visita");
        base.otorgar_permiso(duena, Permiso::AbrirCajaSinLimite).unwrap();
        base.otorgar_permiso(empleada, Permiso::Empleada).unwrap();
        (base, duena, empleada, otro)
    }

    fn m(hora: &str) -> Momento {
        Momento::nuevo("2026-11-25", hora)
    }

    #[test]
    fn turno_el_ultimo_que_abre_se_queda() {
        let mut base = Base::en_memoria_v3().unwrap();
        let primera = base.tomar_turno(None, &m("09:00:00")).unwrap();
        assert!(base.turno_vigente(primera).unwrap());
        let segunda = base.tomar_turno(None, &m("09:30:00")).unwrap();
        assert!(!base.turno_vigente(primera).unwrap(), "la primera caja ya no es la vigente");
        assert!(base.turno_vigente(segunda).unwrap());
    }

    #[test]
    fn permisos_se_otorgan_y_se_quitan() {
        let (mut base, duena, _, _) = base_con_usuarios();
        base.otorgar_permiso(duena, Permiso::AbrirCajaSinLimite).unwrap(); // repetido: no duplica
        assert_eq!(base.permisos(duena).unwrap(), vec![Permiso::AbrirCajaSinLimite]);
        base.quitar_permiso(duena, Permiso::AbrirCajaSinLimite).unwrap();
        assert!(base.permisos(duena).unwrap().is_empty());
    }

    #[test]
    fn reglas_para_abrir_el_cajon() {
        let (mut base, duena, empleada, otro) = base_con_usuarios();
        let hoy = "2026-11-25";
        assert_eq!(base.como_abrir(duena, hoy).unwrap(), Autorizacion::Permiso);
        assert_eq!(base.como_abrir(otro, hoy).unwrap(), Autorizacion::Codigo, "sin permisos de caja: código (D23)");
        // La empleada: una vez al día antes de la primera venta.
        assert_eq!(base.como_abrir(empleada, hoy).unwrap(), Autorizacion::VentanaDiaria);
        base.registrar_apertura(Autorizacion::VentanaDiaria, None, &m("08:55:00"), None).unwrap();
        assert_eq!(base.como_abrir(empleada, hoy).unwrap(), Autorizacion::Codigo, "la ventana diaria ya se usó");
        // Otro día vuelve a tener su ventana… salvo que ya haya ventas ese día.
        assert_eq!(base.como_abrir(empleada, "2026-11-26").unwrap(), Autorizacion::VentanaDiaria);
        base.con.execute("INSERT INTO ventas (fecha, hora, total, recibido, cambio) VALUES ('2026-11-26', '08:00:00', 1, 1, 0)", []).unwrap();
        assert_eq!(base.como_abrir(empleada, "2026-11-26").unwrap(), Autorizacion::Codigo, "ya hubo una venta");
        // La dueña siempre.
        assert_eq!(base.como_abrir(duena, "2026-11-26").unwrap(), Autorizacion::Permiso);
    }

    #[test]
    fn una_apertura_queda_en_el_historial_y_en_el_registro() {
        let (mut base, _, _, _) = base_con_usuarios();
        let id = base.registrar_apertura(Autorizacion::Codigo, None, &m("10:00:00"), None).unwrap();
        let (autorizacion, evento): (String, String) = base
            .con
            .query_row(
                "SELECT a.autorizacion, e.evento FROM aperturas_caja a JOIN eventos_especiales e ON e.id = a.evento_id WHERE a.id = ?1",
                params![id],
                |f| Ok((f.get(0)?, f.get(1)?)),
            )
            .unwrap();
        assert_eq!((autorizacion.as_str(), evento.as_str()), ("codigo", EVENTO_APERTURA));
        let filas = base.ventas_del_dia("2026-11-25", false).unwrap();
        assert_eq!(filas[0].producto, EVENTO_APERTURA, "se ve en VENTAS REALIZADAS como en la v2");
    }

    #[test]
    fn el_codigo_es_de_un_solo_uso_y_no_se_guarda_en_texto() {
        let (mut base, duena, empleada, _) = base_con_usuarios();
        assert_eq!(base.estado_codigo().unwrap(), EstadoCodigo::SinCodigo);
        assert!(matches!(base.usar_codigo("1234", &m("10:00:00"), None), Err(ErrorCaja::SinCodigo)));
        assert!(matches!(base.poner_codigo(empleada, "1234", &m("10:00:00"), None), Err(ErrorCaja::SinPermisoParaElCodigo)));
        assert!(matches!(base.poner_codigo(duena, "12", &m("10:00:00"), None), Err(ErrorCaja::CodigoCorto(4))));
        base.poner_codigo(duena, " 7410 ", &m("10:00:00"), None).unwrap();
        assert_eq!(base.estado_codigo().unwrap(), EstadoCodigo::Disponible);
        let guardado: String = base.con.query_row("SELECT hash || sal FROM codigo_caja", [], |f| f.get(0)).unwrap();
        assert!(!guardado.contains("7410"), "el código no se guarda en texto");
        // Un código incorrecto no lo gasta; el correcto sí, y después queda bloqueado.
        assert!(matches!(base.usar_codigo("0000", &m("10:05:00"), None), Err(ErrorCaja::CodigoIncorrecto)));
        let sesion = base.iniciar_sesion(empleada, &m("09:00:00"), None, None).unwrap();
        base.usar_codigo("7410", &m("10:06:00"), Some(sesion)).unwrap();
        assert_eq!(base.estado_codigo().unwrap(), EstadoCodigo::Usado { usado_en: "2026-11-25 10:06:00".into(), usado_sesion_id: Some(sesion) });
        assert!(matches!(base.usar_codigo("7410", &m("10:07:00"), None), Err(ErrorCaja::CodigoUsado)));
        // Uno nuevo lo vuelve a habilitar.
        base.poner_codigo(duena, "8520", &m("11:00:00"), None).unwrap();
        assert_eq!(base.estado_codigo().unwrap(), EstadoCodigo::Disponible);
        assert!(matches!(base.usar_codigo("7410", &m("11:01:00"), None), Err(ErrorCaja::CodigoIncorrecto)));
    }
}
