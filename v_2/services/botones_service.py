from __future__ import annotations

import os
import sqlite3
from datetime import datetime

from services.identidad import USUARIO_PLANTILLA


class BotonesService:
    def __init__(self, db_path=None):
        if db_path is None:
            db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ventas.db")

        self.db_path = db_path
        self._ensure_schema()

    def _connect(self):
        con = sqlite3.connect(self.db_path)
        con.execute("PRAGMA foreign_keys = ON")
        return con

    def _normalizar_usuario(self, usuario):
        return str(usuario).strip().lower()

    def _ensure_schema(self):
        # Solo estructura -- este servicio no siembra datos de negocio (que
        # botones existen, quien los ve). Hay un solo ventas.db real y ese
        # tipo de dato se administra a mano desde el panel o con un script
        # puntual, no con una maquinaria de migraciones automaticas.
        with self._connect() as con:
            cur = con.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS botones (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre_interno TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    etiqueta       TEXT NOT NULL,
                    archivo_accion TEXT NOT NULL,
                    orden          INTEGER NOT NULL DEFAULT 0,
                    activo         INTEGER NOT NULL DEFAULT 1,
                    creado_en      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    actualizado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS boton_visibilidad (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    boton_id   INTEGER NOT NULL REFERENCES botones(id) ON DELETE CASCADE,
                    usuario_id INTEGER NOT NULL REFERENCES usuarios_sistema(id) ON DELETE CASCADE,
                    UNIQUE(boton_id, usuario_id)
                )
                """
            )
            con.commit()

    def _obtener_usuario_id(self, cur, nombre_usuario):
        cur.execute(
            "SELECT id FROM usuarios_sistema WHERE nombre_usuario = ? ORDER BY id ASC LIMIT 1",
            (self._normalizar_usuario(nombre_usuario),),
        )
        fila = cur.fetchone()
        return int(fila[0]) if fila else None

    def obtener_usuario_id(self, nombre_usuario):
        with self._connect() as con:
            return self._obtener_usuario_id(con.cursor(), nombre_usuario)

    # ---- botones ----

    def listar_botones(self, solo_activos=False):
        with self._connect() as con:
            cur = con.cursor()
            consulta = "SELECT id, nombre_interno, etiqueta, archivo_accion, orden, activo FROM botones"
            if solo_activos:
                consulta += " WHERE activo = 1"
            consulta += " ORDER BY orden ASC, etiqueta COLLATE NOCASE ASC"
            cur.execute(consulta)
            return [tuple(fila) for fila in cur.fetchall()]

    def crear_boton(self, nombre_interno, etiqueta, archivo_accion, orden=0):
        nombre_interno = str(nombre_interno).strip().lower()
        etiqueta = str(etiqueta).strip()
        archivo_accion = str(archivo_accion).strip()
        if not nombre_interno or not etiqueta or not archivo_accion:
            raise ValueError("nombre_interno, etiqueta y archivo_accion son obligatorios.")

        ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self._connect() as con:
                cur = con.cursor()
                cur.execute(
                    """
                    INSERT INTO botones (nombre_interno, etiqueta, archivo_accion, orden, actualizado_en)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (nombre_interno, etiqueta, archivo_accion, int(orden), ahora),
                )
                boton_id = cur.lastrowid
                con.commit()
        except sqlite3.IntegrityError:
            raise ValueError(f"Ya existe un boton para el archivo '{archivo_accion}'.")

        return boton_id

    def editar_boton(self, boton_id, etiqueta=None, archivo_accion=None, orden=None):
        campos = []
        valores = []
        if etiqueta is not None:
            campos.append("etiqueta = ?")
            valores.append(str(etiqueta).strip())
        if archivo_accion is not None:
            campos.append("archivo_accion = ?")
            valores.append(str(archivo_accion).strip())
        if orden is not None:
            campos.append("orden = ?")
            valores.append(int(orden))
        if not campos:
            return False

        campos.append("actualizado_en = ?")
        valores.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        valores.append(int(boton_id))

        with self._connect() as con:
            cur = con.cursor()
            cur.execute(f"UPDATE botones SET {', '.join(campos)} WHERE id = ?", valores)
            cambios = cur.rowcount
            con.commit()

        return cambios > 0

    def establecer_activo(self, boton_id, activo):
        with self._connect() as con:
            cur = con.cursor()
            cur.execute(
                "UPDATE botones SET activo = ?, actualizado_en = ? WHERE id = ?",
                (1 if activo else 0, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), int(boton_id)),
            )
            cambios = cur.rowcount
            con.commit()

        return cambios > 0

    def eliminar_boton(self, boton_id):
        with self._connect() as con:
            cur = con.cursor()
            cur.execute("DELETE FROM botones WHERE id = ?", (int(boton_id),))
            cambios = cur.rowcount
            con.commit()

        return cambios > 0

    # ---- visibilidad (siempre nombres explicitos; sin comodines) ----

    def listar_visibilidad(self, boton_id):
        with self._connect() as con:
            cur = con.cursor()
            cur.execute(
                """
                SELECT u.nombre_usuario
                FROM boton_visibilidad v
                JOIN usuarios_sistema u ON u.id = v.usuario_id
                WHERE v.boton_id = ?
                """,
                (int(boton_id),),
            )
            return sorted(str(fila[0]) for fila in cur.fetchall())

    def set_visibilidad(self, boton_id, nombres_usuario):
        with self._connect() as con:
            cur = con.cursor()
            cur.execute("DELETE FROM boton_visibilidad WHERE boton_id = ?", (int(boton_id),))
            for nombre in nombres_usuario or []:
                usuario_id = self._obtener_usuario_id(cur, nombre)
                if usuario_id is None:
                    continue
                cur.execute(
                    "INSERT OR IGNORE INTO boton_visibilidad (boton_id, usuario_id) VALUES (?, ?)",
                    (int(boton_id), usuario_id),
                )
            con.commit()

    def listar_botones_visibles_para(self, usuario_id, solo_activos=True):
        with self._connect() as con:
            cur = con.cursor()
            consulta = """
                SELECT DISTINCT b.id, b.etiqueta, b.archivo_accion, b.orden
                FROM botones b
                JOIN boton_visibilidad v ON v.boton_id = b.id
                WHERE v.usuario_id = ?
            """
            parametros = [int(usuario_id)]
            if solo_activos:
                consulta += " AND b.activo = 1"
            consulta += " ORDER BY b.orden ASC, b.etiqueta COLLATE NOCASE ASC"
            cur.execute(consulta, parametros)
            return [tuple(fila) for fila in cur.fetchall()]

    def otorgar_plantilla_a_usuario_nuevo(self, usuario_id):
        # Copia, una sola vez, los botones que hoy tenga el usuario
        # __default__ hacia este usuario_id -- de ahi en adelante son filas
        # propias de usuario_id, editables/quitables individualmente sin
        # afectar a nadie mas (a diferencia de un comodin en vivo).
        with self._connect() as con:
            cur = con.cursor()
            plantilla_id = self._obtener_usuario_id(cur, USUARIO_PLANTILLA)
            if plantilla_id is None or plantilla_id == int(usuario_id):
                return

            cur.execute("SELECT boton_id FROM boton_visibilidad WHERE usuario_id = ?", (plantilla_id,))
            for (boton_id,) in cur.fetchall():
                cur.execute(
                    "INSERT OR IGNORE INTO boton_visibilidad (boton_id, usuario_id) VALUES (?, ?)",
                    (boton_id, int(usuario_id)),
                )
            con.commit()
