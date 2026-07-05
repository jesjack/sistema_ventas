from __future__ import annotations

import getpass
from datetime import datetime
import platform
import socket
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
            db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ventas.db")

        self.db_path = db_path
        self._ensure_schema()

    def _connect(self):
        con = sqlite3.connect(self.db_path)
        con.execute("PRAGMA foreign_keys = ON")
        return con

    def obtener_datos_usuario_sistema(self):
        usuario = self._obtener_nombre_usuario_sistema()
        sistema_operativo = platform.system() or os.name
        version_sistema = platform.version() or platform.release() or ""
        nombre_equipo = socket.gethostname() or ""
        dominio = (
            os.environ.get("USERDOMAIN")
            or os.environ.get("DOMAIN")
            or os.environ.get("COMPUTERDOMAIN")
            or ""
        )

        return {
            "nombre_usuario": usuario,
            "sistema_operativo": sistema_operativo,
            "version_sistema": version_sistema,
            "nombre_equipo": nombre_equipo,
            "dominio": dominio,
        }

    def _obtener_nombre_usuario_sistema(self):
        for obtenedor in (getpass.getuser, os.getlogin):
            try:
                nombre = obtenedor()
                if nombre:
                    return str(nombre)
            except Exception:
                pass

        return str(os.environ.get("USERNAME") or os.environ.get("USER") or "desconocido")

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
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS codigos_barras_registrados (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    codigo_barras  TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    producto_id    INTEGER NOT NULL REFERENCES catalogo_autocompletado(id),
                    precio_venta   REAL NOT NULL,
                    creado_en      TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS usuarios_sistema (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre_usuario    TEXT NOT NULL COLLATE NOCASE,
                    sistema_operativo TEXT NOT NULL,
                    version_sistema   TEXT,
                    nombre_equipo     TEXT,
                    dominio           TEXT,
                    creado_en         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    ultimo_acceso     TEXT,
                    UNIQUE(nombre_usuario, sistema_operativo, nombre_equipo, dominio)
                )
                """
            )
            if not self._tabla_tiene_columnas(
                cur,
                "usuarios_sistema",
                {"sistema_operativo", "version_sistema", "nombre_equipo", "dominio", "creado_en", "ultimo_acceso"},
            ):
                self._migrar_usuarios_sistema(cur)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sesiones_sistema (
                    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario_id            INTEGER NOT NULL REFERENCES usuarios_sistema(id),
                    inicio                TEXT NOT NULL,
                    ultimo_latido         TEXT NOT NULL,
                    salida_real           TEXT,
                    cerrada_correctamente INTEGER NOT NULL DEFAULT 0,
                    pid                   INTEGER,
                    detalle               TEXT
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

    def _migrar_usuarios_sistema(self, cur):
        cur.execute("PRAGMA table_info(usuarios_sistema)")
        columnas_existentes = [fila[1] for fila in cur.fetchall()]
        if not columnas_existentes:
            return

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS usuarios_sistema_nueva (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre_usuario    TEXT NOT NULL COLLATE NOCASE,
                sistema_operativo TEXT NOT NULL,
                version_sistema   TEXT,
                nombre_equipo     TEXT,
                dominio           TEXT,
                creado_en         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                ultimo_acceso     TEXT,
                UNIQUE(nombre_usuario, sistema_operativo, nombre_equipo, dominio)
            )
            """
        )

        columnas_insert = ["id", "nombre_usuario"]
        valores_select = ["id", "nombre_usuario"]

        if "sistema_operativo" in columnas_existentes:
            columnas_insert.append("sistema_operativo")
            valores_select.append("COALESCE(sistema_operativo, 'desconocido')")
        else:
            columnas_insert.append("sistema_operativo")
            valores_select.append("'desconocido'")

        if "version_sistema" in columnas_existentes:
            columnas_insert.append("version_sistema")
            valores_select.append("COALESCE(version_sistema, '')")
        else:
            columnas_insert.append("version_sistema")
            valores_select.append("''")

        if "nombre_equipo" in columnas_existentes:
            columnas_insert.append("nombre_equipo")
            valores_select.append("COALESCE(nombre_equipo, '')")
        else:
            columnas_insert.append("nombre_equipo")
            valores_select.append("''")

        if "dominio" in columnas_existentes:
            columnas_insert.append("dominio")
            valores_select.append("COALESCE(dominio, '')")
        else:
            columnas_insert.append("dominio")
            valores_select.append("''")

        if "creado_en" in columnas_existentes:
            columnas_insert.append("creado_en")
            valores_select.append("creado_en")
        else:
            columnas_insert.append("creado_en")
            valores_select.append("CURRENT_TIMESTAMP")

        if "ultimo_acceso" in columnas_existentes:
            columnas_insert.append("ultimo_acceso")
            valores_select.append("ultimo_acceso")
        else:
            columnas_insert.append("ultimo_acceso")
            valores_select.append("NULL")

        cur.execute(
            f"INSERT INTO usuarios_sistema_nueva ({', '.join(columnas_insert)}) SELECT {', '.join(valores_select)} FROM usuarios_sistema"
        )
        cur.execute("DROP TABLE usuarios_sistema")
        cur.execute("ALTER TABLE usuarios_sistema_nueva RENAME TO usuarios_sistema")

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

    def obtener_codigo_barras_registrado(self, codigo_barras):
        codigo = str(codigo_barras).strip()
        if not codigo:
            return None

        with self._connect() as con:
            cur = con.cursor()
            cur.execute(
                """
                SELECT c.id, c.producto, b.precio_venta
                FROM codigos_barras_registrados b
                JOIN catalogo_autocompletado c ON c.id = b.producto_id
                WHERE b.codigo_barras = ?
                """,
                (codigo,),
            )
            fila = cur.fetchone()

        if fila is None:
            return None

        return int(fila[0]), str(fila[1]), float(fila[2])

    def registrar_codigo_barras(self, codigo_barras, producto_id, precio_venta):
        codigo = str(codigo_barras).strip()
        if not codigo:
            raise ValueError("El codigo de barras no puede estar vacio.")

        with self._connect() as con:
            cur = con.cursor()
            cur.execute(
                "INSERT INTO codigos_barras_registrados (codigo_barras, producto_id, precio_venta) VALUES (?,?,?)",
                (codigo, int(producto_id), float(precio_venta)),
            )
            codigo_id = cur.lastrowid
            con.commit()

        return codigo_id

    def asegurar_usuario_sistema(self, datos_usuario=None):
        datos = datos_usuario or self.obtener_datos_usuario_sistema()
        ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with self._connect() as con:
            cur = con.cursor()
            cur.execute(
                """
                INSERT INTO usuarios_sistema (
                    nombre_usuario,
                    sistema_operativo,
                    version_sistema,
                    nombre_equipo,
                    dominio,
                    ultimo_acceso
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(nombre_usuario, sistema_operativo, nombre_equipo, dominio)
                DO UPDATE SET
                    version_sistema = excluded.version_sistema,
                    ultimo_acceso = excluded.ultimo_acceso
                """,
                (
                    str(datos.get("nombre_usuario", "desconocido")),
                    str(datos.get("sistema_operativo", "desconocido")),
                    str(datos.get("version_sistema", "")),
                    str(datos.get("nombre_equipo", "")),
                    str(datos.get("dominio", "")),
                    ahora,
                ),
            )
            cur.execute(
                """
                SELECT id
                FROM usuarios_sistema
                WHERE nombre_usuario = ?
                  AND sistema_operativo = ?
                  AND COALESCE(nombre_equipo, '') = ?
                  AND COALESCE(dominio, '') = ?
                """,
                (
                    str(datos.get("nombre_usuario", "desconocido")),
                    str(datos.get("sistema_operativo", "desconocido")),
                    str(datos.get("nombre_equipo", "")),
                    str(datos.get("dominio", "")),
                ),
            )
            fila = cur.fetchone()
            con.commit()

        if fila is None:
            raise RuntimeError("No se pudo asegurar el usuario del sistema.")

        return int(fila[0])

    def iniciar_sesion_sistema(self, usuario_id, fecha=None, hora=None, detalle=None, pid=None):
        ahora = datetime.now()
        fecha = fecha or ahora.strftime("%Y-%m-%d")
        hora = hora or ahora.strftime("%H:%M:%S")
        instante = f"{fecha} {hora}"

        with self._connect() as con:
            cur = con.cursor()
            cur.execute(
                """
                INSERT INTO sesiones_sistema (
                    usuario_id,
                    inicio,
                    ultimo_latido,
                    salida_real,
                    cerrada_correctamente,
                    pid,
                    detalle
                ) VALUES (?, ?, ?, NULL, 0, ?, ?)
                """,
                (
                    int(usuario_id),
                    instante,
                    instante,
                    None if pid is None else int(pid),
                    None if detalle is None else str(detalle),
                ),
            )
            sesion_id = cur.lastrowid
            cur.execute(
                "UPDATE usuarios_sistema SET ultimo_acceso = ? WHERE id = ?",
                (instante, int(usuario_id)),
            )
            con.commit()

        return sesion_id

    def registrar_latido_sesion(self, sesion_id, fecha=None, hora=None):
        ahora = datetime.now()
        fecha = fecha or ahora.strftime("%Y-%m-%d")
        hora = hora or ahora.strftime("%H:%M:%S")
        instante = f"{fecha} {hora}"

        with self._connect() as con:
            cur = con.cursor()
            cur.execute(
                """
                UPDATE sesiones_sistema
                SET ultimo_latido = ?
                WHERE id = ?
                """,
                (instante, int(sesion_id)),
            )
            cur.execute(
                """
                UPDATE usuarios_sistema
                SET ultimo_acceso = ?
                WHERE id = (
                    SELECT usuario_id
                    FROM sesiones_sistema
                    WHERE id = ?
                )
                """,
                (instante, int(sesion_id)),
            )
            con.commit()

    def cerrar_sesion_sistema(self, sesion_id, fecha=None, hora=None, detalle=None, exitosa=True):
        ahora = datetime.now()
        fecha = fecha or ahora.strftime("%Y-%m-%d")
        hora = hora or ahora.strftime("%H:%M:%S")
        instante = f"{fecha} {hora}"

        with self._connect() as con:
            cur = con.cursor()
            cur.execute(
                """
                UPDATE sesiones_sistema
                SET ultimo_latido = ?,
                    salida_real = ?,
                    cerrada_correctamente = ?
                WHERE id = ?
                """,
                (instante, instante, 1 if exitosa else 0, int(sesion_id)),
            )
            cur.execute(
                """
                UPDATE usuarios_sistema
                SET ultimo_acceso = ?
                WHERE id = (
                    SELECT usuario_id
                    FROM sesiones_sistema
                    WHERE id = ?
                )
                """,
                (instante, int(sesion_id)),
            )
            con.commit()

    def listar_usuarios_sistema(self):
        with self._connect() as con:
            cur = con.cursor()
            cur.execute(
                """
                SELECT
                    u.id,
                    u.nombre_usuario,
                    u.sistema_operativo,
                    u.version_sistema,
                    u.nombre_equipo,
                    u.dominio,
                    u.creado_en,
                    u.ultimo_acceso,
                    COUNT(s.id) AS total_sesiones,
                    MAX(COALESCE(s.salida_real, s.ultimo_latido, s.inicio)) AS ultima_salida
                FROM usuarios_sistema u
                LEFT JOIN sesiones_sistema s ON s.usuario_id = u.id
                GROUP BY
                    u.id,
                    u.nombre_usuario,
                    u.sistema_operativo,
                    u.version_sistema,
                    u.nombre_equipo,
                    u.dominio,
                    u.creado_en,
                    u.ultimo_acceso
                ORDER BY u.ultimo_acceso DESC, u.nombre_usuario COLLATE NOCASE ASC
                """
            )
            return [tuple(fila) for fila in cur.fetchall()]

    def listar_sesiones_sistema(self, usuario_id=None):
        with self._connect() as con:
            cur = con.cursor()
            consulta_base = """
                SELECT
                    s.id,
                    u.nombre_usuario,
                    u.sistema_operativo,
                    s.inicio,
                    COALESCE(s.salida_real, s.ultimo_latido) AS salida,
                    s.ultimo_latido,
                    s.cerrada_correctamente,
                    CASE
                        WHEN s.cerrada_correctamente = 1 THEN 'cerrada'
                        ELSE 'activa_o_interrumpida'
                    END AS estado,
                    s.pid,
                    s.detalle
                FROM sesiones_sistema s
                JOIN usuarios_sistema u ON u.id = s.usuario_id
            """

            if usuario_id is None:
                cur.execute(f"{consulta_base} ORDER BY s.inicio DESC, s.id DESC")
            else:
                cur.execute(
                    f"{consulta_base} WHERE s.usuario_id = ? ORDER BY s.inicio DESC, s.id DESC",
                    (int(usuario_id),),
                )

            return [tuple(fila) for fila in cur.fetchall()]

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