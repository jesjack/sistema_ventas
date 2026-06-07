#!/usr/bin/env python3
"""
leer_ventas_hoy.py  —  Exporta las ventas del día actual a CSV para LibreOffice Basic
Uso:
    python3 leer_ventas_hoy.py /ruta/ventas.db /tmp/tpv_hoy.csv

CSV de salida (sin encabezado, separado por comas):
    producto,cantidad,precio,subtotal

Cada fila de venta se exporta por separado y se ordena de la hora más antigua
a la más reciente.
"""

import sys
import sqlite3
import csv
import os
from datetime import date

if len(sys.argv) < 3:
    sys.exit("Uso: leer_ventas_hoy.py <db_path> <csv_path>")

db_path  = sys.argv[1]
csv_path = sys.argv[2]
hoy      = date.today().isoformat()   # "2026-06-07"

# Si no existe la BD todavía, crear CSV vacío y salir limpiamente
if not os.path.exists(db_path):
    open(csv_path, "w").close()
    sys.exit(0)

con = sqlite3.connect(db_path)
cur = con.cursor()

# Exportar cada fila de venta por separado, ordenada por hora ascendente
cur.execute("""
    SELECT
        i.producto,
        i.cantidad       AS total_cant,
        i.precio,
        i.subtotal       AS total_sub
    FROM venta_items i
    JOIN ventas v ON v.id = i.venta_id
    WHERE v.fecha = ?
    ORDER BY v.hora ASC, v.id ASC, i.id ASC
""", (hoy,))

filas = cur.fetchall()
con.close()

with open(csv_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    for fila in filas:
        producto = fila[0]
        cantidad = int(fila[1])
        precio   = float(fila[2])
        subtotal = float(fila[3])
        writer.writerow([producto, cantidad, f"{precio:.2f}", f"{subtotal:.2f}"])

print(f"OK {len(filas)} productos exportados para {hoy}")
