from __future__ import annotations

from datetime import datetime
import unicodedata
import re
import os
import sqlite3
from typing import Iterable


PREPOSICIONES_CATALOGO = {
    "de",
    "del",
    "la",
    "el",
    "los",
    "las",
    "un",
    "una",
    "unos",
    "unas",
    "y",
    "o",
}


class VentasService:
    def __init__(self, db_path=None):
        if db_path is None:
            db_path = os.path.join(os.path.dirname(__file__), "ventas.db")

        self.db_path = db_path
        self._ensure_schema()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _ensure_schema(self):
        with self._connect() as con:
            cur = con.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS ventas (
                    id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    fecha    TEXT NOT NULL,
                    hora     TEXT NOT NULL,
                    total    REAL NOT NULL,
                    recibido REAL NOT NULL,
                    cambio   REAL NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS eventos_especiales (
                    id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    fecha    TEXT NOT NULL,
                    hora     TEXT NOT NULL,
                    evento   TEXT NOT NULL,
                    detalle  TEXT
                )
                """
            )
            if self._tabla_tiene_columnas(cur, "autorizaciones_codigos", {"fecha", "hora"}):
                self._migrar_autorizaciones_codigos(cur)
            else:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS autorizaciones_codigos (
                        id        INTEGER PRIMARY KEY AUTOINCREMENT,
                        codigo    TEXT NOT NULL,
                        evento_id INTEGER REFERENCES eventos_especiales(id)
                    )
                    """
                )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS venta_items (
                    id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    venta_id INTEGER NOT NULL REFERENCES ventas(id),
                    producto TEXT NOT NULL,
                    precio   REAL NOT NULL,
                    cantidad INTEGER NOT NULL,
                    subtotal REAL NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS catalogo_autocompletado (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    producto   TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    creado_en  TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            con.commit()

    def _tabla_tiene_columnas(self, cur, nombre_tabla, columnas):
        cur.execute(f"PRAGMA table_info({nombre_tabla})")
        existentes = {fila[1] for fila in cur.fetchall()}
        return bool(existentes) and columnas.issubset(existentes)

    def _migrar_autorizaciones_codigos(self, cur):
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS autorizaciones_codigos_nueva (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo    TEXT NOT NULL,
                evento_id INTEGER REFERENCES eventos_especiales(id)
            )
            """
        )
        cur.execute(
            "INSERT INTO autorizaciones_codigos_nueva (id, codigo, evento_id) SELECT id, codigo, evento_id FROM autorizaciones_codigos"
        )
        cur.execute("DROP TABLE autorizaciones_codigos")
        cur.execute("ALTER TABLE autorizaciones_codigos_nueva RENAME TO autorizaciones_codigos")

    def registrar_venta(self, items: Iterable, recibido=0, cambio=0, fecha=None, hora=None):
        items = list(items)
        if not items:
            return None

        ahora = datetime.now()
        fecha = fecha or ahora.strftime("%Y-%m-%d")
        hora = hora or ahora.strftime("%H:%M:%S")
        total = sum(float(item[3]) for item in items)

        with self._connect() as con:
            cur = con.cursor()
            cur.execute(
                "INSERT INTO ventas (fecha, hora, total, recibido, cambio) VALUES (?,?,?,?,?)",
                (fecha, hora, float(total), float(recibido), float(cambio)),
            )
            venta_id = cur.lastrowid

            for producto, precio, cantidad, subtotal in items:
                cur.execute(
                    "INSERT INTO venta_items (venta_id, producto, precio, cantidad, subtotal) VALUES (?,?,?,?,?)",
                    (venta_id, str(producto), float(precio), int(cantidad), float(subtotal)),
                )

            con.commit()

        return venta_id

    def registrar_evento_especial(self, evento, detalle=None, fecha=None, hora=None):
        ahora = datetime.now()
        fecha = fecha or ahora.strftime("%Y-%m-%d")
        hora = hora or ahora.strftime("%H:%M:%S")

        with self._connect() as con:
            cur = con.cursor()
            cur.execute(
                "INSERT INTO eventos_especiales (fecha, hora, evento, detalle) VALUES (?,?,?,?)",
                (fecha, hora, str(evento), None if detalle is None else str(detalle)),
            )
            event_id = cur.lastrowid
            con.commit()

        return event_id

    def registrar_codigo_autorizacion(self, codigo, evento_id=None, detalle=None, fecha=None, hora=None):
        with self._connect() as con:
            cur = con.cursor()
            cur.execute(
                    "INSERT INTO autorizaciones_codigos (codigo, evento_id) VALUES (?,?)",
                    (str(codigo), evento_id),
            )
            auth_id = cur.lastrowid
            con.commit()

        return auth_id

    def obtener_ventas(self, fecha=None):
        fecha = fecha or datetime.now().strftime("%Y-%m-%d")

        with self._connect() as con:
            cur = con.cursor()
            cur.execute(
                """
                SELECT hora, producto, precio, cantidad, subtotal
                FROM (
                    SELECT
                        v.hora AS hora,
                        i.producto AS producto,
                        i.precio AS precio,
                        i.cantidad AS cantidad,
                        i.subtotal AS subtotal,
                        v.id AS orden_principal,
                        i.id AS orden_secundario,
                        0 AS tipo_registro
                    FROM ventas v
                    JOIN venta_items i ON i.venta_id = v.id
                    WHERE v.fecha = ?

                    UNION ALL

                    SELECT
                        e.hora AS hora,
                        e.evento AS producto,
                        NULL AS precio,
                        NULL AS cantidad,
                        NULL AS subtotal,
                        e.id AS orden_principal,
                        0 AS orden_secundario,
                        1 AS tipo_registro
                    FROM eventos_especiales e
                    WHERE e.fecha = ?
                )
                ORDER BY hora ASC, tipo_registro ASC, orden_principal ASC, orden_secundario ASC
                """,
                (fecha, fecha),
            )
            filas = []
            for hora, producto, precio, cantidad, subtotal in cur.fetchall():
                filas.append(
                    (
                        hora,
                        producto,
                        "" if precio is None else precio,
                        "" if cantidad is None else cantidad,
                        "" if subtotal is None else subtotal,
                    )
                )
            return filas

    def listar_catalogo_autocompletado(self):
        with self._connect() as con:
            cur = con.cursor()
            cur.execute(
                """
                SELECT id, producto
                FROM catalogo_autocompletado
                ORDER BY producto COLLATE NOCASE ASC
                """
            )
            return [(int(fila[0]), str(fila[1])) for fila in cur.fetchall()]

    def buscar_catalogo_autocompletado(self, prefijo=None, limite=20):
        texto = "" if prefijo is None else str(prefijo).strip().lower()
        limite = max(1, int(limite))

        with self._connect() as con:
            cur = con.cursor()
            if texto:
                cur.execute(
                    """
                    SELECT id, producto
                    FROM catalogo_autocompletado
                    WHERE producto LIKE ? COLLATE NOCASE
                    ORDER BY producto COLLATE NOCASE ASC
                    LIMIT ?
                    """,
                    (f"{texto}%", limite),
                )
            else:
                cur.execute(
                    """
                    SELECT id, producto
                    FROM catalogo_autocompletado
                    ORDER BY producto COLLATE NOCASE ASC
                    LIMIT ?
                    """,
                    (limite,),
                )

            return [(int(fila[0]), str(fila[1])) for fila in cur.fetchall()]

    def _normalizar_iniciales(self, texto):
        partes = re.findall(r"[\wÁÉÍÓÚÜÑáéíóúüñ]+", str(texto).strip().lower(), flags=re.UNICODE)
        iniciales = []

        for parte in partes:
            if parte in PREPOSICIONES_CATALOGO:
                continue
            iniciales.append(parte[:1])

        return "".join(iniciales)

    def _normalizar_prefijo_usuario(self, texto):
        texto = str(texto).strip().lower()
        if not texto:
            return ""

        normalizado = unicodedata.normalize("NFD", texto)
        sin_acentos = "".join(caracter for caracter in normalizado if unicodedata.category(caracter) != "Mn")
        return "".join(caracter for caracter in sin_acentos if caracter.isalnum())

    def buscar_catalogo_por_iniciales(self, iniciales, limite=20):
        prefijo = self._normalizar_prefijo_usuario(iniciales)
        limite = max(1, int(limite))

        if not prefijo:
            return []

        coincidencias = []
        for producto_id, producto in self.listar_catalogo_autocompletado():
            iniciales_producto = self._normalizar_iniciales(producto)
            if iniciales_producto.startswith(prefijo):
                coincidencias.append((producto_id, producto))
                if len(coincidencias) >= limite:
                    break

        return coincidencias

    def agregar_producto_autocompletado(self, producto):
        nombre = str(producto).strip().lower()
        if not nombre:
            raise ValueError("El producto no puede estar vacio.")

        with self._connect() as con:
            cur = con.cursor()
            cur.execute(
                "INSERT INTO catalogo_autocompletado (producto) VALUES (?)",
                (nombre,),
            )
            producto_id = cur.lastrowid
            con.commit()

        return producto_id

    def editar_producto_autocompletado(self, producto_id, nuevo_nombre):
        nombre = str(nuevo_nombre).strip().lower()
        if not nombre:
            raise ValueError("El producto no puede estar vacio.")

        with self._connect() as con:
            cur = con.cursor()
            cur.execute(
                "UPDATE catalogo_autocompletado SET producto = ? WHERE id = ?",
                (nombre, int(producto_id)),
            )
            cambios = cur.rowcount
            con.commit()

        return cambios > 0

    def eliminar_producto_autocompletado(self, producto_id):
        with self._connect() as con:
            cur = con.cursor()
            cur.execute(
                "DELETE FROM catalogo_autocompletado WHERE id = ?",
                (int(producto_id),),
            )
            cambios = cur.rowcount
            con.commit()

        return cambios > 0