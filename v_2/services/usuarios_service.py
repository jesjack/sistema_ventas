"""Usuarios del sistema operativo que abren el POS y sus sesiones."""

from __future__ import annotations

import os
import platform
import socket
from datetime import datetime

from services.identidad import obtener_usuario_actual, usuario_existe_en_sistema, USUARIO_PLANTILLA
from services.servicio_bd import ServicioBD


class UsuariosService(ServicioBD):
    def obtener_datos_usuario_sistema(self):
        usuario = obtener_usuario_actual()
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

    def asegurar_usuario_sistema(self, datos_usuario=None):
        # Devuelve (usuario_id, es_nuevo). "es_nuevo" es True si esta exacta
        # combinacion nombre_usuario+sistema_operativo+equipo+dominio no
        # existia todavia -- lo usa BotonesService para saber cuando copiarle
        # a alguien la plantilla de botones (usuario __default__) una sola
        # vez, en su primer login.
        datos = datos_usuario or self.obtener_datos_usuario_sistema()
        ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        nombre_usuario = str(datos.get("nombre_usuario", "desconocido"))
        sistema_operativo = str(datos.get("sistema_operativo", "desconocido"))
        version_sistema = str(datos.get("version_sistema", ""))
        nombre_equipo = str(datos.get("nombre_equipo", ""))
        dominio = str(datos.get("dominio", ""))

        with self._connect() as con:
            cur = con.cursor()
            cur.execute(
                """
                SELECT id
                FROM usuarios_sistema
                WHERE nombre_usuario = ?
                  AND sistema_operativo = ?
                  AND COALESCE(nombre_equipo, '') = ?
                  AND COALESCE(dominio, '') = ?
                """,
                (nombre_usuario, sistema_operativo, nombre_equipo, dominio),
            )
            fila = cur.fetchone()
            es_nuevo = fila is None

            if es_nuevo:
                cur.execute(
                    """
                    INSERT INTO usuarios_sistema
                        (nombre_usuario, sistema_operativo, version_sistema, nombre_equipo, dominio, ultimo_acceso)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (nombre_usuario, sistema_operativo, version_sistema, nombre_equipo, dominio, ahora),
                )
                usuario_id = cur.lastrowid
            else:
                usuario_id = int(fila[0])
                cur.execute(
                    "UPDATE usuarios_sistema SET version_sistema = ?, ultimo_acceso = ?, activo = 1 WHERE id = ?",
                    (version_sistema, ahora, usuario_id),
                )

            con.commit()

        return usuario_id, es_nuevo

    def sincronizar_usuarios_con_sistema(self):
        # Marca activo=0 a los usuarios de este equipo que ya no existen como
        # cuenta del sistema operativo (y reactiva a los que reaparecen). No
        # borra filas: sesiones_sistema y boton_visibilidad dependen de ellas.
        # Devuelve la cantidad de filas cuyo estado cambio.
        datos = self.obtener_datos_usuario_sistema()
        cambios = 0

        with self._connect() as con:
            cur = con.cursor()
            cur.execute(
                """
                SELECT id, nombre_usuario, activo
                FROM usuarios_sistema
                WHERE nombre_usuario <> ?
                  AND sistema_operativo = ?
                  AND COALESCE(nombre_equipo, '') = ?
                """,
                (USUARIO_PLANTILLA, datos["sistema_operativo"], datos["nombre_equipo"]),
            )
            for usuario_id, nombre_usuario, activo in cur.fetchall():
                existe = usuario_existe_en_sistema(nombre_usuario)
                if existe is None:
                    continue

                nuevo_estado = 1 if existe else 0
                if nuevo_estado != int(activo):
                    con.execute("UPDATE usuarios_sistema SET activo = ? WHERE id = ?", (nuevo_estado, usuario_id))
                    cambios += 1

            con.commit()

        return cambios

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
                    cerrada_correctamente = ?,
                    detalle = COALESCE(?, detalle)
                WHERE id = ?
                """,
                (
                    instante,
                    instante,
                    1 if exitosa else 0,
                    None if detalle is None else str(detalle),
                    int(sesion_id),
                ),
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

    def listar_usuarios_sistema(self, solo_activos=True):
        filtro = "WHERE u.activo = 1" if solo_activos else ""
        with self._connect() as con:
            cur = con.cursor()
            cur.execute(
                f"""
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
                {filtro}
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
