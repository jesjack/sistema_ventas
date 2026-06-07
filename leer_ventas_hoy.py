#!/usr/bin/env python3
"""
leer_ventas_hoy.py  —  Exporta las ventas del día actual a CSV para LibreOffice Basic
Uso:
    python3 leer_ventas_hoy.py /ruta/ventas.db /tmp/tpv_hoy.csv

CSV de salida (sin encabezado, separado por comas):
    producto,cantidad,precio,subtotal

Los productos se agrupan: si el mismo producto aparece en varias ventas del día
se suman las cantidades y subtotales.
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

# Agrupar por producto: suma de cantidad y subtotal para las ventas de hoy
cur.execute("""
    SELECT
        i.producto,
        SUM(i.cantidad)  AS total_cant,
        i.precio,
        SUM(i.subtotal)  AS total_sub
    FROM venta_items i
    JOIN ventas v ON v.id = i.venta_id
    WHERE v.fecha = ?
    GROUP BY i.producto, i.precio
    ORDER BY i.producto
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
