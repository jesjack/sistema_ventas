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
    con.commit()
    con.close()
    print(f"Base de prueba creada en {DESTINO} ({len(PRODUCTOS)} productos, {len(CODIGOS)} códigos).")


if __name__ == "__main__":
    main()
