//! Ver y asignar los permisos de caja (D21) sin escribir nombres en el código.
//!
//! Uso (desde v_3/nucleo):
//!   cargo run --bin permisos -- <base de la v3>                          lista usuarios y permisos
//!   cargo run --bin permisos -- <base de la v3> <usuario> <permiso>      otorga
//!   cargo run --bin permisos -- <base de la v3> <usuario> <permiso> quitar
//!
//! Permisos: desarrollador · abrir_caja_sin_limite · empleada. El usuario es el nombre de usuario
//! del sistema de ESTE equipo; si nunca ha abierto la caja aquí, se registra de antemano.
//! Provisional: más adelante será una pantalla de administración (D21).

use std::process::ExitCode;

use nucleo::Base;
use nucleo::caja::Permiso;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let Some(ruta) = args.first() else {
        eprintln!("Uso: permisos <base de la v3> [<usuario> <permiso> [quitar]]");
        return ExitCode::from(2);
    };
    let mut base = match Base::abrir_v3(ruta) {
        Ok(b) => b,
        Err(e) => {
            eprintln!("No se pudo abrir {ruta}: {e}");
            return ExitCode::FAILURE;
        }
    };
    if let [_, usuario, permiso, resto @ ..] = args.as_slice() {
        let Some(permiso) = Permiso::TODOS.into_iter().find(|p| p.clave() == permiso) else {
            eprintln!("Permiso desconocido: {permiso}. Válidos: desarrollador, abrir_caja_sin_limite, empleada");
            return ExitCode::from(2);
        };
        let resultado = base.usuario_de_este_equipo(usuario).and_then(|(id, nuevo)| {
            if nuevo {
                println!("{usuario} no había abierto la caja en este equipo: registrado (id {id}).");
            }
            if resto.first().map(String::as_str) == Some("quitar") {
                base.quitar_permiso(id, permiso)
            } else {
                base.otorgar_permiso(id, permiso)
            }
        });
        if let Err(e) = resultado {
            eprintln!("No se pudo cambiar el permiso: {e}");
            return ExitCode::FAILURE;
        }
    }
    match base.usuarios_con_permisos() {
        Ok(lista) => {
            for (id, nombre, permisos) in lista {
                let p: Vec<&str> = permisos.iter().map(|p| p.clave()).collect();
                println!("{id:>5}  {nombre:<32} {}", if p.is_empty() { "—".to_string() } else { p.join(", ") });
            }
            ExitCode::SUCCESS
        }
        Err(e) => {
            eprintln!("No se pudieron leer los usuarios: {e}");
            ExitCode::FAILURE
        }
    }
}
