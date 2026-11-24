//! Importa los datos de una base de la v2 a una base NUEVA de la v3.
//!
//! Uso: `cargo run --release --bin importar_v2 -- <base de la v2> <base nueva de la v3>`
//!
//! La base de la v2 se abre en solo lectura y no se modifica. La de la v3 no debe existir.

use std::process::ExitCode;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let [origen, destino] = args.as_slice() else {
        eprintln!("Uso: importar_v2 <base de la v2> <base nueva de la v3>");
        return ExitCode::from(2);
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
            ExitCode::SUCCESS
        }
        Err(e) => {
            eprintln!("No se pudo importar: {e}");
            ExitCode::FAILURE
        }
    }
}
