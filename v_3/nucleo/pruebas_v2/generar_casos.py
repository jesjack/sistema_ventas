"""Genera los casos con los que se prueba el núcleo de la v3 CONTRA LA V2.

Ejecuta el código real de la v2 (`table_modules/carrito.py`, `dialogs/parseo.py`,
`services/ventas_service.py`, `services/esquema.py`) y guarda en `casos_v2.json` las entradas y lo
que la v2 devolvió. Las pruebas de Rust (`tests/contra_v2.rs`) repiten las mismas operaciones y
comparan. Si una regla de la v3 se aparta de la v2, falla la prueba.

**No toca ninguna base real:** la v2 trabaja sobre una base temporal que se borra al final. De esa
base se guarda también el esquema (`esquema_v2.sql`), para que las pruebas de Rust creen el mismo.

Uso (desde v_3/nucleo):  python3 -I pruebas_v2/generar_casos.py [ruta de v_2]
Por defecto, ~/sistema_ventas/v_2. Volver a correrlo si cambia la v2.
"""

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

V2 = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "sistema_ventas" / "v_2"
AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(V2))

from dialogs.parseo import parse_monto  # noqa: E402
from dialogs.varios_codigos import filtrar_productos  # noqa: E402
from services.catalogo_service import CatalogoService, ProductoDuplicado, formatear_nombre  # noqa: E402
from services.codigos_barras_service import CodigoDuplicado, CodigosBarrasService  # noqa: E402
from services.ventas_service import VentasService  # noqa: E402
from table_modules.carrito import agregar_al_carrito, total_del_carrito  # noqa: E402


class Tabla(list):
    """La v2 opera sobre tablas de la hoja con interfaz de lista; una lista basta."""


def casos_carrito():
    """Secuencias de entradas (producto, precio, cantidad) y el carrito que deja la v2 tras cada una."""
    secuencias = [
        [["blusa", 150.0, 1]],
        [["blusa", 150.0, 1], ["blusa", 150.0, 2]],  # mismo producto y precio: suma cantidades
        [["blusa", 150.0, 1], ["blusa", 120.0, 1]],  # mismo producto, otro precio: fila nueva
        [["blusa", 150.0, 1], ["Blusa", 150.0, 1]],  # mayúsculas: la v2 los trata como distintos
        [["", 150.0, 1], ["faja", 0, 1], ["faja", 200.0, 0], ["faja", 200.0, 1]],  # incompletas: no entran
        [["pantalón", 99.9, 3], ["calcetas", 40.5, 2], ["pantalón", 99.9, 1]],
    ]
    casos = []
    for entradas in secuencias:
        carrito = Tabla()
        pasos = []
        for producto, precio, cantidad in entradas:
            entrada = Tabla([[producto, precio, cantidad]])
            agregado = agregar_al_carrito(entrada, carrito)
            pasos.append({
                "entrada": [producto, precio, cantidad],
                "agregado": agregado,
                "carrito": [list(f) for f in carrito],
                "total": total_del_carrito(carrito),
            })
        casos.append(pasos)
    return casos


def casos_monto():
    textos = ["100", "12.5", "12,5", "1,234.50", "1.234,50", " 200 ", "1 000", "", "   ", "abc", "-5", "0", "1e3"]
    casos = []
    for texto in textos:
        try:
            casos.append({"texto": texto, "valor": parse_monto(texto)})
        except ValueError:
            casos.append({"texto": texto, "error": True})
    return casos


def casos_ventas(db: Path):
    """Ventas, eventos y un corte de caja en una base temporal; lo que devuelve obtener_ventas."""
    servicio = VentasService(db_path=str(db), sesion_id=None)
    operaciones = [
        {"op": "venta", "items": [["blusa", 150.0, 1, 150.0], ["faja", 200.0, 2, 400.0]], "recibido": 600.0, "cambio": 50.0, "fecha": "2026-11-20", "hora": "10:15:02"},
        {"op": "evento", "evento": "APERTURA DE CAJA", "detalle": "Se abrió la caja desde el botón de la hoja.", "fecha": "2026-11-20", "hora": "10:20:00"},
        {"op": "venta", "items": [["calcetas", 40.0, 3, 120.0]], "recibido": 120.0, "cambio": 0.0, "fecha": "2026-11-20", "hora": "12:40:51"},
        {"op": "corte", "cambio": [["BILLETE", 500, 1], ["MONEDA", 10, 3], ["MONEDA", 0.5, 0]], "fecha": "2026-11-20", "hora": "14:00:00"},
        {"op": "venta", "items": [["chamarra", 450.0, 1, 450.0]], "recibido": 500.0, "cambio": 50.0, "fecha": "2026-11-20", "hora": "15:30:10"},
        {"op": "evento", "evento": "APERTURA DE CAJA", "detalle": None, "fecha": "2026-11-20", "hora": "15:30:10"},
        {"op": "venta", "items": [["blusa", 150.0, 1, 150.0]], "recibido": 150.0, "cambio": 0.0, "fecha": "2026-11-21", "hora": "09:00:00"},
        {"op": "venta", "items": [], "recibido": 0.0, "cambio": 0.0, "fecha": "2026-11-21", "hora": "09:05:00"},  # vacía: no se registra
    ]
    resultados = []
    for o in operaciones:
        if o["op"] == "venta":
            r = servicio.registrar_venta(o["items"], recibido=o["recibido"], cambio=o["cambio"], fecha=o["fecha"], hora=o["hora"])
        elif o["op"] == "evento":
            r = servicio.registrar_evento_especial(o["evento"], detalle=o["detalle"], fecha=o["fecha"], hora=o["hora"])
        else:
            r = servicio.registrar_corte_de_caja(o["cambio"], fecha=o["fecha"], hora=o["hora"])
        resultados.append(r)

    def filas(fecha, desde_ultimo_corte):
        return [list(f) for f in servicio.obtener_ventas(fecha=fecha, desde_ultimo_corte=desde_ultimo_corte)]

    con = sqlite3.connect(db)
    tablas = {
        t: [list(f) for f in con.execute(f"SELECT * FROM {t} ORDER BY id")]
        for t in ("ventas", "venta_items", "eventos_especiales", "cortes_caja", "cortes_caja_cambio")
    }
    con.close()
    return {
        "operaciones": operaciones,
        "resultados": resultados,
        "obtener_ventas": {
            "2026-11-20 completo": filas("2026-11-20", False),
            "2026-11-20 desde_corte": filas("2026-11-20", True),
            "2026-11-21 completo": filas("2026-11-21", False),
            "2026-11-22 completo": filas("2026-11-22", False),
        },
        "tablas": tablas,
    }


CATALOGO = [
    "blusa basica", "Blusa Básica de Licra", "blusa de rayas", "mayón de faja", "mayon deportivo",
    "pantalón de mezclilla", "calcetas y medias", "chamarra", "short", "faja", "vestido corto",
]


def casos_textos():
    nombres = CATALOGO + ["  mayon   de faja ", "LA BLUSA DEL PUEBLO", "ñandú", ""]
    productos = list(enumerate(CATALOGO, start=1))
    busquedas = ["bb", "bdl", "b b", "bbl", "faja", "Faja", "mayon", "mayón", "pdm", "cym", "c y m", "", "  ", "xyz", "ón", "dep"]
    return {
        "formatear_nombre": [{"texto": n, "formateado": formatear_nombre(n)} for n in nombres],
        "buscar": [{"texto": b, "ids": [i for i, _ in filtrar_productos(productos, b)]} for b in busquedas],
    }


def casos_catalogo(db: Path):
    """Productos y códigos de barras en la base temporal. Las columnas con la hora del momento
    (creado_en, actualizado_en) no se comparan."""
    catalogo = CatalogoService(db_path=str(db), sesion_id=None)
    codigos = CodigosBarrasService(db_path=str(db), sesion_id=None)
    pasos = []

    def paso(op, args, fn):
        try:
            pasos.append({"op": op, "args": args, "resultado": fn()})
        except ProductoDuplicado:
            pasos.append({"op": op, "args": args, "error": "producto_duplicado"})
        except CodigoDuplicado:
            pasos.append({"op": op, "args": args, "error": "codigo_duplicado"})
        except ValueError:
            pasos.append({"op": op, "args": args, "error": "vacio"})
        except sqlite3.IntegrityError:
            pasos.append({"op": op, "args": args, "error": "integridad"})

    for nombre in ["Blusa Básica", "  faja  ", "chamarra", "BLUSA BÁSICA", "", "Faja"]:
        paso("agregar_producto", [nombre], lambda n=nombre: catalogo.agregar_producto_autocompletado(n))
    paso("editar_producto", [3, "  Chamarra Larga "], lambda: catalogo.editar_producto_autocompletado(3, "  Chamarra Larga "))
    paso("editar_producto", [3, "FAJA"], lambda: catalogo.editar_producto_autocompletado(3, "FAJA"))
    paso("editar_producto", [99, "nada"], lambda: catalogo.editar_producto_autocompletado(99, "nada"))
    for codigo, producto, precio in [(" 7501000000011 ", 1, 150), ("mayfaj", 2, 200.5), ("MAYFAJ", 2, 99), ("", 1, 1), ("c md", 3, 180)]:
        paso("registrar_codigo", [codigo, producto, precio], lambda c=codigo, p=producto, x=precio: codigos.registrar_codigo_barras(c, p, x))
    for codigo in ["7501000000011", " 7501000000011", "MAYFAJ", "mayfaj", "C MD", "nada", ""]:
        paso("obtener_codigo", [codigo], lambda c=codigo: (lambda r: None if r is None else list(r))(codigos.obtener_codigo_barras_registrado(c)))
    paso("actualizar_codigo", [2, "c md", 2, 210], lambda: codigos.actualizar_codigo_barras(2, "c md", 2, 210))
    paso("actualizar_codigo", [2, "mayfaj2", 2, 210], lambda: codigos.actualizar_codigo_barras(2, "mayfaj2", 2, 210))
    for filtro in ["", "faja", "MAY", "básica", "750", "nada"]:
        paso("listar_codigos", [filtro], lambda f=filtro: [[c.id, c.codigo_barras, c.producto_id, c.producto, c.precio_venta] for c in codigos.listar_codigos_barras(f)])
    paso("listar_productos", [], lambda: [list(p) for p in catalogo.listar_catalogo_autocompletado()])

    con = sqlite3.connect(db)
    tablas = {
        "catalogo_autocompletado": [list(f) for f in con.execute("SELECT id, producto, sesion_id, actualizado_sesion_id FROM catalogo_autocompletado ORDER BY id")],
        "codigos_barras_registrados": [list(f) for f in con.execute("SELECT id, codigo_barras, producto_id, precio_venta, sesion_id, actualizado_sesion_id FROM codigos_barras_registrados ORDER BY id")],
    }
    con.close()
    return {"pasos": pasos, "tablas": tablas}


def main():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "ventas.db"
        ventas = casos_ventas(db)  # crea el esquema de la v2 (asegurar_esquema) en la base temporal
        db_catalogo = Path(tmp) / "catalogo.db"
        catalogo = casos_catalogo(db_catalogo)
        con = sqlite3.connect(db)
        esquema = [sql for (sql,) in con.execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type DESC, name")]
        con.close()
    (AQUI / "esquema_v2.sql").write_text(";\n\n".join(esquema) + ";\n", encoding="utf-8")
    casos = {"carrito": casos_carrito(), "monto": casos_monto(), "ventas": ventas, "textos": casos_textos(), "catalogo": catalogo}
    (AQUI / "casos_v2.json").write_text(json.dumps(casos, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Casos: {len(casos['carrito'])} de carrito, {len(casos['monto'])} de monto, "
          f"{len(ventas['operaciones'])} operaciones de ventas, {len(catalogo['pasos'])} de catálogo. Esquema: {len(esquema)} sentencias.")


if __name__ == "__main__":
    main()
