//! Pruebas CONTRA LA V2: repiten las operaciones de `pruebas_v2/casos_v2.json` (generado
//! ejecutando el código real de la v2 con `pruebas_v2/generar_casos.py`) y comparan resultados,
//! incluido el contenido exacto de las tablas que deja cada operación.

use rusqlite::types::ValueRef;
use serde_json::{Value, json};

use crate::base::Base;
use crate::carrito::{Carrito, FilaCarrito};
use crate::catalogo::{ErrorCatalogo, formatear_nombre};
use crate::cobro::leer_monto;
use crate::corte::PiezaCambio;
use crate::sesiones::DatosUsuario;
use crate::ventas::{FilaVentas, Momento};

const CASOS: &str = include_str!("../pruebas_v2/casos_v2.json");
const ESQUEMA_V2: &str = include_str!("../pruebas_v2/esquema_v2.sql");

fn casos() -> Value {
    serde_json::from_str(CASOS).expect("casos_v2.json válido")
}

fn base_v2() -> Base {
    let base = Base::en_memoria().unwrap();
    base.ejecutar_sql(ESQUEMA_V2).unwrap();
    base
}

fn numero(v: &Value) -> f64 {
    v.as_f64().unwrap_or(0.0)
}

#[test]
fn el_esquema_de_la_v2_es_compatible() {
    base_v2().verificar_esquema().unwrap();
}

#[test]
fn carrito_como_la_v2() {
    for (n, secuencia) in casos()["carrito"].as_array().unwrap().iter().enumerate() {
        let mut carrito = Carrito::nuevo();
        for paso in secuencia.as_array().unwrap() {
            let e = &paso["entrada"];
            let agregado = carrito.agregar(e[0].as_str().unwrap(), numero(&e[1]), e[2].as_i64().unwrap_or(0));
            assert_eq!(agregado, paso["agregado"].as_bool().unwrap(), "secuencia {n}, entrada {e}");
            let esperado: Vec<FilaCarrito> = paso["carrito"]
                .as_array()
                .unwrap()
                .iter()
                .map(|f| FilaCarrito {
                    producto: f[0].as_str().unwrap().to_string(),
                    precio: numero(&f[1]),
                    cantidad: f[2].as_i64().unwrap(),
                    subtotal: numero(&f[3]),
                })
                .collect();
            assert_eq!(carrito.filas, esperado, "secuencia {n}, entrada {e}");
            assert_eq!(carrito.total(), numero(&paso["total"]), "secuencia {n}");
        }
    }
}

#[test]
fn montos_como_la_v2() {
    for caso in casos()["monto"].as_array().unwrap() {
        let texto = caso["texto"].as_str().unwrap();
        let esperado = if caso["error"].as_bool() == Some(true) { None } else { Some(numero(&caso["valor"])) };
        assert_eq!(leer_monto(texto), esperado, "texto {texto:?}");
    }
}

/// Una fila de VENTAS REALIZADAS como la devuelve la v2: "" donde no hay valor.
fn fila_v2(f: &FilaVentas) -> Value {
    let o = |v: Option<Value>| v.unwrap_or(json!(""));
    json!([f.hora, f.producto, o(f.precio.map(Value::from)), o(f.cantidad.map(Value::from)), o(f.subtotal.map(Value::from))])
}

fn volcar(base: &Base, tabla: &str) -> Value {
    let mut consulta = base.con.prepare(&format!("SELECT * FROM {tabla} ORDER BY id")).unwrap();
    let columnas = consulta.column_count();
    let filas = consulta
        .query_map([], |f| {
            Ok((0..columnas)
                .map(|i| match f.get_ref(i).unwrap() {
                    ValueRef::Null => Value::Null,
                    ValueRef::Integer(n) => json!(n),
                    ValueRef::Real(x) => json!(x),
                    ValueRef::Text(t) => json!(String::from_utf8_lossy(t)),
                    ValueRef::Blob(_) => Value::Null,
                })
                .collect::<Vec<_>>())
        })
        .unwrap()
        .map(Result::unwrap)
        .collect::<Vec<_>>();
    json!(filas)
}

#[test]
fn ventas_eventos_y_corte_como_la_v2() {
    let casos = casos();
    let ventas = &casos["ventas"];
    let mut base = base_v2();
    for (op, esperado) in ventas["operaciones"].as_array().unwrap().iter().zip(ventas["resultados"].as_array().unwrap()) {
        let momento = Momento::nuevo(op["fecha"].as_str().unwrap(), op["hora"].as_str().unwrap());
        let obtenido = match op["op"].as_str().unwrap() {
            "venta" => {
                let items: Vec<FilaCarrito> = op["items"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|i| FilaCarrito {
                        producto: i[0].as_str().unwrap().into(),
                        precio: numero(&i[1]),
                        cantidad: i[2].as_i64().unwrap(),
                        subtotal: numero(&i[3]),
                    })
                    .collect();
                json!(base.registrar_venta(&items, numero(&op["recibido"]), numero(&op["cambio"]), &momento, None).unwrap())
            }
            "evento" => json!(base.registrar_evento(op["evento"].as_str().unwrap(), op["detalle"].as_str(), &momento, None).unwrap()),
            _ => {
                let cambio: Vec<PiezaCambio> = op["cambio"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|p| PiezaCambio { tipo: p[0].as_str().unwrap().into(), denominacion: numero(&p[1]), cantidad: p[2].as_i64().unwrap() })
                    .collect();
                json!(base.registrar_corte(&cambio, &momento, None).unwrap())
            }
        };
        assert_eq!(&obtenido, esperado, "operación {op}");
    }

    for (clave, esperado) in ventas["obtener_ventas"].as_object().unwrap() {
        let (fecha, modo) = clave.split_once(' ').unwrap();
        let filas: Vec<Value> = base.ventas_del_dia(fecha, modo == "desde_corte").unwrap().iter().map(fila_v2).collect();
        assert_eq!(&json!(filas), esperado, "obtener_ventas {clave}");
    }

    for (tabla, esperado) in ventas["tablas"].as_object().unwrap() {
        assert_eq!(&volcar(&base, tabla), esperado, "tabla {tabla}");
    }
}

#[test]
fn nombres_y_busqueda_como_la_v2() {
    let casos = casos();
    for caso in casos["textos"]["formatear_nombre"].as_array().unwrap() {
        let texto = caso["texto"].as_str().unwrap();
        assert_eq!(formatear_nombre(texto), caso["formateado"].as_str().unwrap(), "texto {texto:?}");
    }
    // El catálogo de la v2 en el mismo orden (ids 1..n); buscar_productos ordena alfabéticamente,
    // así que se compara el CONJUNTO de ids que coinciden, con `coincide`.
    let nombres = ["blusa basica", "Blusa Básica de Licra", "blusa de rayas", "mayón de faja", "mayon deportivo",
        "pantalón de mezclilla", "calcetas y medias", "chamarra", "short", "faja", "vestido corto"];
    for caso in casos["textos"]["buscar"].as_array().unwrap() {
        let texto = caso["texto"].as_str().unwrap();
        let obtenidos: Vec<i64> = nombres.iter().enumerate().filter(|(_, n)| crate::catalogo::coincide(n, texto)).map(|(i, _)| i as i64 + 1).collect();
        let esperados: Vec<i64> = caso["ids"].as_array().unwrap().iter().map(|v| v.as_i64().unwrap()).collect();
        assert_eq!(obtenidos, esperados, "búsqueda {texto:?}");
    }
}

/// Un error de la v3 en el mismo vocabulario que el generador. La v2 da un IntegrityError suelto al
/// REGISTRAR un código repetido y CodigoDuplicado al EDITARLO: en la v3 los dos son CodigoDuplicado.
fn error_v2(e: &ErrorCatalogo, op: &str) -> &'static str {
    match e {
        ErrorCatalogo::ProductoVacio | ErrorCatalogo::CodigoVacio => "vacio",
        ErrorCatalogo::ProductoDuplicado => "producto_duplicado",
        ErrorCatalogo::CodigoDuplicado if op == "registrar_codigo" => "integridad",
        ErrorCatalogo::CodigoDuplicado => "codigo_duplicado",
        ErrorCatalogo::Base(_) => "base",
    }
}

#[test]
fn catalogo_y_codigos_como_la_v2() {
    let casos = casos();
    let mut base = base_v2();
    for paso in casos["catalogo"]["pasos"].as_array().unwrap() {
        let op = paso["op"].as_str().unwrap();
        let a = &paso["args"];
        let texto = |i: usize| a[i].as_str().unwrap().to_string();
        let resultado: Result<Value, ErrorCatalogo> = match op {
            "agregar_producto" => base.agregar_producto(&texto(0), None).map(Value::from),
            "editar_producto" => base.editar_producto(a[0].as_i64().unwrap(), &texto(1), None).map(Value::from),
            "registrar_codigo" => base.registrar_codigo(&texto(0), a[1].as_i64().unwrap(), numero(&a[2]), None).map(Value::from),
            "actualizar_codigo" => base.actualizar_codigo(a[0].as_i64().unwrap(), &texto(1), a[2].as_i64().unwrap(), numero(&a[3]), None).map(Value::from),
            "obtener_codigo" => Ok(base.buscar_codigo(&texto(0)).unwrap().map_or(Value::Null, |c| json!([c.producto_id, c.producto, c.precio]))),
            "listar_codigos" => Ok(json!(base.codigos(&texto(0)).unwrap().iter()
                .map(|c| json!([c.id, c.codigo, c.producto_id, c.producto, c.precio])).collect::<Vec<_>>())),
            "listar_productos" => Ok(json!(base.productos().unwrap().iter().map(|p| json!([p.id, p.nombre])).collect::<Vec<_>>())),
            otra => panic!("operación desconocida {otra}"),
        };
        match (resultado, paso.get("error")) {
            (Ok(v), None) => assert_eq!(&v, &paso["resultado"], "{op} {a}"),
            (Err(e), Some(esperado)) => assert_eq!(error_v2(&e, op), esperado.as_str().unwrap(), "{op} {a}"),
            (r, _) => panic!("{op} {a}: la v3 dio {r:?} y la v2 {paso}"),
        }
    }
    let tablas = &casos["catalogo"]["tablas"];
    let consulta = |sql: &str| -> Value {
        let mut c = base.con.prepare(sql).unwrap();
        let n = c.column_count();
        json!(c.query_map([], |f| Ok((0..n).map(|i| match f.get_ref(i).unwrap() {
            ValueRef::Null => Value::Null,
            ValueRef::Integer(x) => json!(x),
            ValueRef::Real(x) => json!(x),
            ValueRef::Text(t) => json!(String::from_utf8_lossy(t)),
            ValueRef::Blob(_) => Value::Null,
        }).collect::<Vec<_>>())).unwrap().map(Result::unwrap).collect::<Vec<_>>())
    };
    assert_eq!(consulta("SELECT id, producto, sesion_id, actualizado_sesion_id FROM catalogo_autocompletado ORDER BY id"), tablas["catalogo_autocompletado"]);
    assert_eq!(consulta("SELECT id, codigo_barras, producto_id, precio_venta, sesion_id, actualizado_sesion_id FROM codigos_barras_registrados ORDER BY id"), tablas["codigos_barras_registrados"]);
}

/// La base REAL (una copia) es compatible y se puede leer. Solo a petición, porque necesita la
/// base: `CAJA_DB=../app/datos/ventas_copia.db cargo test -- --ignored`. No escribe nada.
#[test]
#[ignore]
fn la_base_real_es_compatible() {
    let ruta = std::env::var("CAJA_DB").expect("CAJA_DB con la ruta de una COPIA de ventas.db");
    let base = Base::abrir_solo_lectura(&ruta).unwrap();
    base.verificar_esquema().unwrap();
    let productos = base.productos().unwrap();
    let dias = base.dias_con_ventas(30).unwrap();
    let filas = base.ventas_del_dia(&dias[0], false).unwrap();
    println!("{} productos, {} días con ventas; el {}: {} filas", productos.len(), dias.len(), dias[0], filas.len());
    assert!(!productos.is_empty() && !filas.is_empty());
}

#[test]
fn usuarios_y_sesiones_como_la_v2() {
    let casos = casos();
    let mut base = base_v2();
    for paso in casos["usuarios"]["pasos"].as_array().unwrap() {
        let a = &paso["args"];
        let momento = || Momento::nuevo(a[1].as_str().unwrap(), a[2].as_str().unwrap());
        match paso["op"].as_str().unwrap() {
            "asegurar_usuario" => {
                let d = &paso["datos"];
                let t = |k: &str| d[k].as_str().unwrap().to_string();
                let datos = DatosUsuario {
                    nombre_usuario: t("nombre_usuario"),
                    sistema_operativo: t("sistema_operativo"),
                    version_sistema: t("version_sistema"),
                    nombre_equipo: t("nombre_equipo"),
                    dominio: t("dominio"),
                };
                let (id, nuevo) = base.asegurar_usuario(&datos).unwrap();
                assert_eq!(json!([id, nuevo]), paso["resultado"], "{datos:?}");
            }
            "iniciar_sesion" => {
                let id = base.iniciar_sesion(a[0].as_i64().unwrap(), &momento(), a[3].as_i64(), a[4].as_str()).unwrap();
                assert_eq!(json!(id), paso["resultado"]);
            }
            "latido" => base.latido(a[0].as_i64().unwrap(), &momento()).unwrap(),
            "cerrar_sesion" => base.cerrar_sesion(a[0].as_i64().unwrap(), &momento(), a[3].as_str(), a[4].as_bool().unwrap()).unwrap(),
            otra => panic!("operación desconocida {otra}"),
        }
    }
    let tablas = &casos["usuarios"]["tablas"];
    let consulta = |sql: &str| -> Value {
        let mut c = base.con.prepare(sql).unwrap();
        let n = c.column_count();
        json!(c.query_map([], |f| Ok((0..n).map(|i| match f.get_ref(i).unwrap() {
            ValueRef::Null => Value::Null,
            ValueRef::Integer(x) => json!(x),
            ValueRef::Real(x) => json!(x),
            ValueRef::Text(t) => json!(String::from_utf8_lossy(t)),
            ValueRef::Blob(_) => Value::Null,
        }).collect::<Vec<_>>())).unwrap().map(Result::unwrap).collect::<Vec<_>>())
    };
    // El usuario plantilla trae el último acceso de cuando se generaron los casos: se compara sin él.
    let mut usuarios = consulta("SELECT id, nombre_usuario, sistema_operativo, version_sistema, nombre_equipo, dominio, ultimo_acceso, activo FROM usuarios_sistema ORDER BY id");
    let mut esperados = tablas["usuarios_sistema"].clone();
    for filas in [&mut usuarios, &mut esperados] {
        filas[0][6] = Value::Null;
    }
    assert_eq!(usuarios, esperados);
    assert_eq!(consulta("SELECT * FROM sesiones_sistema ORDER BY id"), tablas["sesiones_sistema"]);
}
