#!/bin/bash
# ver_ventas_hoy.sh — Muestra las ventas del día desde ventas.db
# Uso: bash ver_ventas_hoy.sh [ruta/a/ventas.db]

DB="${1:-ventas.db}"
HOY=$(date +%Y-%m-%d)

if [ ! -f "$DB" ]; then
    echo "❌ No se encontró: $DB"
    echo "   Uso: bash ver_ventas_hoy.sh /ruta/a/ventas.db"
    exit 1
fi

echo ""
echo "══════════════════════════════════════════════════"
echo "  VENTAS DEL DÍA — $HOY"
echo "══════════════════════════════════════════════════"

sqlite3 "$DB" <<SQL
.mode column
.headers on
.width 5 8 8 9 9 8

SELECT
    v.id        AS "Venta#",
    v.hora      AS "Hora",
    v.total     AS "Total",
    v.recibido  AS "Recibido",
    v.cambio    AS "Cambio",
    COUNT(i.id) AS "Artículos"
FROM ventas v
JOIN venta_items i ON i.venta_id = v.id
WHERE v.fecha = '$HOY'
GROUP BY v.id
ORDER BY v.hora;

SQL

echo ""
echo "──────────────────────────────────────────────────"

sqlite3 "$DB" <<SQL
.mode column
.headers off

SELECT
    'Ventas realizadas : ' || COUNT(DISTINCT v.id),
    'Total del día     : $' || printf('%.2f', SUM(v.total))
FROM ventas v
WHERE v.fecha = '$HOY';

SQL

echo "══════════════════════════════════════════════════"
echo ""
echo "  DETALLE POR VENTA"
echo "══════════════════════════════════════════════════"

sqlite3 "$DB" <<SQL
.mode column
.headers on
.width 5 8 22 8 6 9

SELECT
    i.venta_id  AS "Venta#",
    v.hora      AS "Hora",
    i.producto  AS "Producto",
    i.precio    AS "Precio",
    i.cantidad  AS "Cant",
    i.subtotal  AS "Subtotal"
FROM venta_items i
JOIN ventas v ON v.id = i.venta_id
WHERE v.fecha = '$HOY'
ORDER BY i.venta_id, i.id;

SQL

echo "══════════════════════════════════════════════════"
echo ""
