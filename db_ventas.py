#!/usr/bin/env python3
import sys
import json
import sqlite3
import os
import traceback

LOG = "/tmp/tpv_error.log"

def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

try:
    log("=== db_ventas.py iniciado ===")
    log(f"argv: {sys.argv}")

    if len(sys.argv) < 2:
        log("ERROR: sin argumento de ruta JSON")
        sys.exit(1)

    ruta_json = sys.argv[1]
    log(f"Leyendo: {ruta_json}")

    with open(ruta_json, "r", encoding="utf-8") as f:
        contenido = f.read()

    log(f"Contenido JSON:\n{contenido}")

    datos = json.loads(contenido)

    db_path  = datos.get("db_path", "ventas.db")
    fecha    = datos.get("fecha", "")
    hora     = datos.get("hora", "")
    total    = float(datos.get("total", 0))
    recibido = float(datos.get("recibido", 0))
    cambio   = float(datos.get("cambio", 0))
    items    = datos.get("items", [])

    log(f"db_path={db_path}  fecha={fecha}  hora={hora}  total={total}  items={len(items)}")

    con = sqlite3.connect(db_path)
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ventas (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha    TEXT NOT NULL,
            hora     TEXT NOT NULL,
            total    REAL NOT NULL,
            recibido REAL NOT NULL,
            cambio   REAL NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS venta_items (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            venta_id INTEGER NOT NULL REFERENCES ventas(id),
            producto TEXT NOT NULL,
            precio   REAL NOT NULL,
            cantidad INTEGER NOT NULL,
            subtotal REAL NOT NULL
        )
    """)

    con.commit()

    cur.execute(
        "INSERT INTO ventas (fecha, hora, total, recibido, cambio) VALUES (?,?,?,?,?)",
        (fecha, hora, total, recibido, cambio)
    )
    venta_id = cur.lastrowid

    for item in items:
        cur.execute(
            "INSERT INTO venta_items (venta_id, producto, precio, cantidad, subtotal) VALUES (?,?,?,?,?)",
            (venta_id, item.get("producto",""), float(item.get("precio",0)),
             int(item.get("cantidad",1)), float(item.get("subtotal",0)))
        )

    con.commit()
    con.close()

    try:
        os.remove(ruta_json)
    except Exception:
        pass

    log(f"OK venta_id={venta_id}")

except Exception:
    log("EXCEPCIÓN:\n" + traceback.format_exc())
    sys.exit(1)
