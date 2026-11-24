"""Crea una base de PRUEBA para el prototipo (datos/ventas_copia.db) con productos inventados.

Sirve para trabajar fuera de la caja, donde no está la base real. En la caja, la copia se saca
de la base real con `copiar_base_real.py` (solo lectura sobre la original).

Uso:  python3 scripts/crear_base_demo.py   (desde v_3/app)
No sobrescribe una base existente salvo con --forzar.
"""

import sqlite3
import sys
from pathlib import Path

DESTINO = Path(__file__).resolve().parent.parent / "datos" / "ventas_copia.db"

# Solo las tablas que lee el prototipo, con el mismo esquema que la v2.
ESQUEMA = """
CREATE TABLE catalogo_autocompletado (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    producto   TEXT NOT NULL UNIQUE COLLATE NOCASE,
    creado_en  TEXT DEFAULT CURRENT_TIMESTAMP,
    sesion_id INTEGER, actualizado_en TEXT, actualizado_sesion_id INTEGER
);
CREATE TABLE codigos_barras_registrados (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo_barras TEXT NOT NULL UNIQUE COLLATE NOCASE,
    producto_id   INTEGER NOT NULL REFERENCES catalogo_autocompletado(id),
    precio_venta  REAL NOT NULL,
    creado_en     TEXT DEFAULT CURRENT_TIMESTAMP,
    sesion_id INTEGER, actualizado_en TEXT, actualizado_sesion_id INTEGER
);
CREATE TABLE ventas (
    id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT NOT NULL, hora TEXT NOT NULL,
    total REAL NOT NULL, recibido REAL NOT NULL, cambio REAL NOT NULL, sesion_id INTEGER
);
CREATE TABLE venta_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT, venta_id INTEGER NOT NULL REFERENCES ventas(id),
    producto TEXT NOT NULL, precio REAL NOT NULL, cantidad INTEGER NOT NULL, subtotal REAL NOT NULL
);
"""

PRODUCTOS = [
    "blusa basica", "blusa de licra", "blusa de rayas", "blusa de terciopelo", "blusa de tirantes",
    "blusa juvenil", "blusa mesh", "blusa mexicana", "pantalon de mezclilla", "pantalon cargo",
    "short deportivo", "falda plisada", "vestido corto", "vestido largo", "sudadera con gorro",
    "playera estampada", "calcetas", "mayon deportivo", "faja", "chamarra",
]
# (código, producto, precio): incluye códigos de texto como los que se imprimen en la caja.
CODIGOS = [
    ("7501000000011", "blusa basica", 150.0),
    ("7501000000028", "pantalon de mezclilla", 350.0),
    ("demo1", "faja", 200.0),
    ("c md", "mayon deportivo", 180.0),
]


# (fecha, hora, recibido, [(producto, precio, cantidad)]): ventas inventadas para VENTAS REALIZADAS.
VENTAS = [
    ("2026-11-20", "10:15:02", 200.0, [("blusa basica", 150.0, 1)]),
    ("2026-11-20", "12:40:51", 500.0, [("pantalon de mezclilla", 350.0, 1), ("calcetas", 40.0, 2)]),
    ("2026-11-21", "17:05:33", 200.0, [("faja", 200.0, 1)]),
]


def main() -> None:
    if DESTINO.exists() and "--forzar" not in sys.argv:
        print(f"Ya existe {DESTINO}; usa --forzar para reemplazarla.")
        return
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.unlink(missing_ok=True)
    con = sqlite3.connect(DESTINO)
    con.executescript(ESQUEMA)
    con.executemany("INSERT INTO catalogo_autocompletado (producto) VALUES (?)", [(p,) for p in PRODUCTOS])
    ids = dict(con.execute("SELECT producto, id FROM catalogo_autocompletado"))
    con.executemany(
        "INSERT INTO codigos_barras_registrados (codigo_barras, producto_id, precio_venta) VALUES (?, ?, ?)",
        [(c, ids[p], precio) for c, p, precio in CODIGOS],
    )
    for fecha, hora, recibido, items in VENTAS:
        total = sum(p * c for _, p, c in items)
        venta = con.execute(
            "INSERT INTO ventas (fecha, hora, total, recibido, cambio) VALUES (?, ?, ?, ?, ?)",
            (fecha, hora, total, recibido, recibido - total),
        ).lastrowid
        con.executemany(
            "INSERT INTO venta_items (venta_id, producto, precio, cantidad, subtotal) VALUES (?, ?, ?, ?, ?)",
            [(venta, prod, p, c, p * c) for prod, p, c in items],
        )
    con.commit()
    con.close()
    print(f"Base de prueba creada en {DESTINO} ({len(PRODUCTOS)} productos, {len(CODIGOS)} códigos, {len(VENTAS)} ventas).")


if __name__ == "__main__":
    main()
