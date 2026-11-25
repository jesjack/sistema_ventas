//! Importar los datos de la v2 a una base NUEVA de la v3.
//!
//! La base de la v2 se abre en SOLO LECTURA y nunca se modifica. Se copian sus tablas conservando
//! los ids (las ventas, sesiones y códigos siguen siendo los mismos números), con las columnas que
//! tengan en común (una v2 vieja puede no tener alguna). `autorizaciones_codigos` no se copia: guarda
//! los códigos en texto plano y la v3 no los quiere (D20/D21).
//!
//! Se usa para la prueba en paralelo (importar una foto de la v2) y una última vez el día que la v3
//! entre a producción.

use std::path::Path;

use rusqlite::params;

use crate::base::{Base, ErrorBase};

/// Las tablas que se copian, en un orden que respeta sus referencias.
pub const TABLAS: &[&str] = &[
    "usuarios_sistema",
    "sesiones_sistema",
    "ventas",
    "venta_items",
    "eventos_especiales",
    "cortes_caja",
    "cortes_caja_cambio",
    "catalogo_autocompletado",
    "codigos_barras_registrados",
    "impresiones_codigos_barras",
    "botones",
    "boton_visibilidad",
];

/// Cuántas filas se copiaron de cada tabla, y las referencias rotas que ya traía la v2.
#[derive(Debug, Clone, PartialEq)]
pub struct Resumen {
    pub filas: Vec<(String, i64)>,
    /// Filas de la v2 que apuntan a algo que no existe (p. ej. una sesión borrada). Se copian igual;
    /// se informan para que se sepa que vienen así de origen.
    pub referencias_rotas: i64,
}

/// Crea en `destino` una base nueva de la v3 con los datos de la base de la v2 en `origen`.
/// `destino` no debe existir: así nunca se mezcla con datos que ya estaban.
pub fn desde_v2(origen: impl AsRef<Path>, destino: impl AsRef<Path>) -> Result<Resumen, ErrorBase> {
    let (origen, destino) = (origen.as_ref(), destino.as_ref());
    if destino.exists() {
        return Err(ErrorBase::Incompatible(format!("{} ya existe: la importación crea una base nueva", destino.display())));
    }
    if !origen.exists() {
        return Err(ErrorBase::Incompatible(format!("no existe la base de la v2 en {}", origen.display())));
    }
    let mut base = Base::abrir_v3(destino)?;
    // La v2, en solo lectura (URI con mode=ro).
    let uri = format!("file:{}?mode=ro", origen.display());
    base.con.execute("ATTACH DATABASE ?1 AS v2", params![uri])?;

    // Las referencias se comprueban al final (la v2 puede traer alguna rota de origen).
    base.con.pragma_update(None, "foreign_keys", false)?;
    let mut filas = Vec::new();
    let tx = base.con.transaction()?;
    // La base nueva trae el usuario plantilla de la migración 1: se reemplaza por los de la v2.
    tx.execute("DELETE FROM main.usuarios_sistema", [])?;
    for tabla in TABLAS {
        let en_v2: i64 = tx.query_row("SELECT count(*) FROM v2.sqlite_master WHERE type = 'table' AND name = ?1", params![tabla], |f| f.get(0))?;
        if en_v2 == 0 {
            filas.push((tabla.to_string(), 0));
            continue;
        }
        // Las columnas que existen en las dos (una v2 vieja puede no tener alguna).
        let comunes: Vec<String> = {
            let mut c_main = tx.prepare(&format!("PRAGMA main.table_info({tabla})"))?;
            let main: Vec<String> = c_main.query_map([], |f| f.get(1))?.collect::<Result<_, _>>()?;
            let mut c_v2 = tx.prepare(&format!("PRAGMA v2.table_info({tabla})"))?;
            let v2: Vec<String> = c_v2.query_map([], |f| f.get(1))?.collect::<Result<_, _>>()?;
            main.into_iter().filter(|c| v2.contains(c)).collect()
        };
        let lista = comunes.iter().map(|c| format!("\"{c}\"")).collect::<Vec<_>>().join(", ");
        let n = tx.execute(&format!("INSERT INTO main.{tabla} ({lista}) SELECT {lista} FROM v2.{tabla} ORDER BY id"), [])?;
        filas.push((tabla.to_string(), n as i64));
    }
    tx.commit()?;
    let referencias_rotas: i64 = {
        let mut consulta = base.con.prepare("PRAGMA main.foreign_key_check")?;
        consulta.query_map([], |_| Ok(()))?.count() as i64
    };
    base.con.pragma_update(None, "foreign_keys", true)?;
    base.con.execute("DETACH DATABASE v2", [])?;
    Ok(Resumen { filas, referencias_rotas })
}

#[cfg(test)]
mod pruebas {
    use super::*;
    use crate::carrito::FilaCarrito;
    use crate::corte::PiezaCambio;
    use crate::sesiones::DatosUsuario;
    use crate::ventas::Momento;
    use std::path::PathBuf;

    /// Una carpeta temporal propia de cada prueba (se borra al terminar).
    struct Carpeta(PathBuf);
    impl Carpeta {
        fn nueva(nombre: &str) -> Self {
            let ruta = std::env::temp_dir().join(format!("nucleo-{nombre}-{}", std::process::id()));
            let _ = std::fs::remove_dir_all(&ruta);
            std::fs::create_dir_all(&ruta).unwrap();
            Self(ruta)
        }
    }
    impl Drop for Carpeta {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    /// Todas las filas de una tabla (columnas en común entre las dos bases), como texto comparable.
    fn filas(base: &Base, tabla: &str, columnas: &[String]) -> Vec<String> {
        let lista = columnas.iter().map(|c| format!("quote(\"{c}\")")).collect::<Vec<_>>().join(" || '|' || ");
        let mut consulta = base.con.prepare(&format!("SELECT {lista} FROM {tabla} ORDER BY id")).unwrap();
        consulta.query_map([], |f| f.get(0)).unwrap().map(Result::unwrap).collect()
    }

    fn nombres_columnas(base: &Base, tabla: &str) -> Vec<String> {
        let mut c = base.con.prepare(&format!("PRAGMA table_info({tabla})")).unwrap();
        c.query_map([], |f| f.get(1)).unwrap().map(Result::unwrap).collect()
    }

    /// Compara cada tabla importada con la de la v2, fila por fila.
    fn comparar(v2: &Base, v3: &Base) {
        for tabla in TABLAS {
            let en_v2 = nombres_columnas(v2, tabla);
            if en_v2.is_empty() {
                // La tabla no existe en esa v2 (p. ej. una base sin botones): en la v3 queda vacía.
                let n: i64 = v3.con.query_row(&format!("SELECT count(*) FROM {tabla}"), [], |f| f.get(0)).unwrap();
                assert_eq!(n, 0, "tabla {tabla}");
                continue;
            }
            let comunes: Vec<String> = nombres_columnas(v3, tabla).into_iter().filter(|c| en_v2.contains(c)).collect();
            assert_eq!(filas(v3, tabla, &comunes), filas(v2, tabla, &comunes), "tabla {tabla}");
        }
    }

    #[test]
    fn importa_todo_conservando_ids_y_sin_tocar_la_v2() {
        let carpeta = Carpeta::nueva("importar");
        let ruta_v2 = carpeta.0.join("v2.db");
        {
            let mut v2 = Base::abrir(&ruta_v2).unwrap();
            v2.ejecutar_sql(include_str!("../pruebas_v2/esquema_v2.sql")).unwrap();
            let datos = |n: &str| DatosUsuario {
                nombre_usuario: n.into(),
                sistema_operativo: "Linux".into(),
                version_sistema: "#1 SMP ".into(),
                nombre_equipo: "caja".into(),
                dominio: String::new(),
            };
            let (ana, _) = v2.asegurar_usuario(&datos("ana")).unwrap();
            let (beto, _) = v2.asegurar_usuario(&datos("beto")).unwrap();
            let m = Momento::nuevo("2026-11-20", "10:00:00");
            let s1 = v2.iniciar_sesion(ana, &m, Some(10), None).unwrap();
            let s2 = v2.iniciar_sesion(beto, &m, None, Some("otra")).unwrap();
            v2.cerrar_sesion(s1, &Momento::nuevo("2026-11-20", "18:00:00"), None, true).unwrap();
            let item = |p: &str, precio: f64, c: i64| FilaCarrito { producto: p.into(), precio, cantidad: c, subtotal: precio * c as f64 };
            v2.registrar_venta(&[item("blusa", 150.0, 1), item("faja", 200.0, 2)], 600.0, 50.0, &m, Some(s1)).unwrap();
            v2.registrar_evento("APERTURA DE CAJA", Some("botón"), &m, Some(s2)).unwrap();
            v2.registrar_corte(&[PiezaCambio { tipo: "BILLETE".into(), denominacion: 500.0, cantidad: 1 }], &m, Some(s1)).unwrap();
            let p = v2.agregar_producto("Blusa Básica", Some(s1)).unwrap();
            v2.registrar_codigo("7501", p, 150.0, Some(s1)).unwrap();
            // Algo que NO debe pasar a la v3: un código de autorización en texto plano.
            v2.ejecutar_sql("INSERT INTO autorizaciones_codigos (codigo, evento_id) VALUES ('5931', 1)").unwrap();
        }
        let antes = std::fs::read(&ruta_v2).unwrap();
        let ruta_v3 = carpeta.0.join("v3.db");
        let resumen = desde_v2(&ruta_v2, &ruta_v3).unwrap();
        assert_eq!(std::fs::read(&ruta_v2).unwrap(), antes, "la base de la v2 cambió");
        assert_eq!(resumen.referencias_rotas, 0);

        let v2 = Base::abrir_solo_lectura(&ruta_v2).unwrap();
        let v3 = Base::abrir_v3(&ruta_v3).unwrap();
        comparar(&v2, &v3);
        assert_eq!(v3.version_esquema().unwrap(), crate::esquema::version_actual());
        let tablas_v3: i64 = v3.con.query_row("SELECT count(*) FROM sqlite_master WHERE name = 'autorizaciones_codigos'", [], |f| f.get(0)).unwrap();
        assert_eq!(tablas_v3, 0, "autorizaciones_codigos no debe existir en la v3");
        // La v3 sigue numerando después de lo importado.
        let mut v3 = v3;
        let nueva = v3.registrar_venta(&[FilaCarrito { producto: "x".into(), precio: 1.0, cantidad: 1, subtotal: 1.0 }], 1.0, 0.0, &Momento::nuevo("2026-11-21", "09:00:00"), None).unwrap();
        assert_eq!(nueva, Some(2));
    }

    #[test]
    fn no_importa_sobre_una_base_que_ya_existe() {
        let carpeta = Carpeta::nueva("importar-existe");
        let (v2, v3) = (carpeta.0.join("v2.db"), carpeta.0.join("v3.db"));
        std::fs::write(&v2, b"").unwrap();
        std::fs::write(&v3, b"").unwrap();
        let error = desde_v2(&v2, &v3).unwrap_err().to_string();
        assert!(error.contains("ya existe"), "{error}");
    }

    /// Importa una COPIA de la base real y la compara tabla por tabla. Solo a petición:
    /// `CAJA_DB=../app/datos/ventas_copia.db cargo test -- --ignored importa_la_base_real`.
    #[test]
    #[ignore]
    fn importa_la_base_real() {
        let origen = std::env::var("CAJA_DB").expect("CAJA_DB con la ruta de una COPIA de ventas.db de la v2");
        let carpeta = Carpeta::nueva("importar-real");
        let destino = carpeta.0.join("v3.db");
        let resumen = desde_v2(&origen, &destino).unwrap();
        println!("{resumen:?}");
        let v2 = Base::abrir_solo_lectura(&origen).unwrap();
        let v3 = Base::abrir_v3(&destino).unwrap();
        comparar(&v2, &v3);
        let total = |b: &Base| -> f64 { b.con.query_row("SELECT COALESCE(SUM(total), 0) FROM ventas", [], |f| f.get(0)).unwrap() };
        assert_eq!(total(&v3), total(&v2));
    }
}
