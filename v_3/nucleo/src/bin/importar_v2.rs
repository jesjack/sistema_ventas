//! Importa los datos de una base de la v2 a una base NUEVA de la v3.
//!
//! Uso: `cargo run --release --bin importar_v2 -- <base de la v2> <base nueva de la v3> [--conservar <base v3 anterior>]`
//!
//! La base de la v2 se abre en solo lectura y no se modifica. La de la v3 no debe existir. Con
//! `--conservar`, después de importar se traen de la base anterior de la v3 (en solo lectura) los
//! permisos, los botones, los códigos de caja y las correcciones (`importar::conservar_de_v3`).

use std::process::ExitCode;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let (origen, destino, anterior) = match args.as_slice() {
        [o, d] => (o, d, None),
        [o, d, bandera, a] if bandera == "--conservar" => (o, d, Some(a)),
        _ => {
            eprintln!("Uso: importar_v2 <base de la v2> <base nueva de la v3> [--conservar <base v3 anterior>]");
            return ExitCode::from(2);
        }
    };
    match nucleo::importar::desde_v2(origen, destino) {
        Ok(resumen) => {
            println!("Importado de {origen} a {destino}:");
            for (tabla, filas) in &resumen.filas {
                println!("  {tabla:<28} {filas:>7} filas");
            }
            if resumen.referencias_rotas > 0 {
                println!("  ({} referencias rotas que ya traía la v2)", resumen.referencias_rotas);
            }
            let Some(anterior) = anterior else { return ExitCode::SUCCESS };
            let conservado = nucleo::Base::abrir_v3(destino).and_then(|mut b| nucleo::importar::conservar_de_v3(anterior, &mut b));
            match conservado {
                Ok(c) => {
                    println!("Conservado de {anterior}:");
                    println!("  permisos {} · botones {} (visibilidad {}) · códigos de caja {} · correcciones {} · usuarios creados {}",
                        c.permisos, c.botones, c.visibilidad, c.codigos_caja, c.correcciones, c.usuarios_nuevos);
                    ExitCode::SUCCESS
                }
                Err(e) => {
                    eprintln!("Se importó, pero no se pudo conservar lo de la v3 anterior: {e}");
                    ExitCode::FAILURE
                }
            }
        }
        Err(e) => {
            eprintln!("No se pudo importar: {e}");
            ExitCode::FAILURE
        }
    }
}
