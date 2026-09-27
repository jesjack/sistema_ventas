from __future__ import annotations

import os
import sqlite3

RAIZ_PROYECTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# En share/, no en la raiz del proyecto: es la carpeta con permisos de lectoescritura para
# todos los usuarios del POS (ver sync_open_system_desktop.sh, fix_share_permissions). Antes
# vivia en la raiz, escribible solo por su dueno -- ahi fallaba prebake_ventas.py para
# cualquiera que no fuera ese usuario ("attempt to write a readonly database"), porque corre
# como quien abre el sistema, no como root (a diferencia de main.py). 2026-09-24.
DB_POR_DEFECTO = os.path.join(RAIZ_PROYECTO, "share", "ventas.db")


def ruta_db(db_path=None):
    return DB_POR_DEFECTO if db_path is None else db_path


def conectar(db_path=None):
    con = sqlite3.connect(ruta_db(db_path))
    con.execute("PRAGMA foreign_keys = ON")
    return con


def tabla_tiene_columnas(cur, nombre_tabla, columnas):
    cur.execute(f"PRAGMA table_info({nombre_tabla})")
    existentes = {fila[1] for fila in cur.fetchall()}
    return bool(existentes) and columnas.issubset(existentes)
