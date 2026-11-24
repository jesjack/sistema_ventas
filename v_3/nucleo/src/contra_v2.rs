//! Pruebas CONTRA LA V2: repiten las operaciones de `pruebas_v2/casos_v2.json` (generado
//! ejecutando el código real de la v2 con `pruebas_v2/generar_casos.py`) y comparan resultados,
//! incluido el contenido exacto de las tablas que deja cada operación.

use rusqlite::types::ValueRef;
use serde_json::{Value, json};

use crate::base::Base;
use crate::carrito::{Carrito, FilaCarrito};
use crate::cobro::leer_monto;
use crate::corte::PiezaCambio;
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
