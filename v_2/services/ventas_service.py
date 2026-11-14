"""Ventas, eventos especiales del historial y codigos de autorizacion."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from services.corte_caja import producto_de_cambio, resumen_del_cambio
from services.servicio_bd import ServicioBD

EVENTO_CORTE = "CORTE DE CAJA"


class VentasService(ServicioBD):
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
                "INSERT INTO ventas (fecha, hora, total, recibido, cambio, sesion_id) VALUES (?,?,?,?,?,?)",
                (fecha, hora, float(total), float(recibido), float(cambio), self.sesion_id),
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
                "INSERT INTO eventos_especiales (fecha, hora, evento, detalle, sesion_id) VALUES (?,?,?,?,?)",
                (fecha, hora, str(evento), None if detalle is None else str(detalle), self.sesion_id),
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

    def registrar_corte_de_caja(self, cambio, fecha=None, hora=None):
        """Corte de caja: desde aquí, obtener_ventas(desde_ultimo_corte=True) deja de mostrar lo
        vendido antes y empieza con `cambio` ([(tipo, denominacion, cantidad), ...], lo que se
        dejó en la caja). También queda un evento "CORTE DE CAJA" en el historial, que se ve al
        revisar el día completo. Devuelve el id del corte."""
        cambio = [(str(tipo), float(denom), int(cant)) for tipo, denom, cant in cambio]
        ahora = datetime.now()
        fecha = fecha or ahora.strftime("%Y-%m-%d")
        hora = hora or ahora.strftime("%H:%M:%S")

        with self._connect() as con:
            cur = con.cursor()
            cur.execute(
                "INSERT INTO eventos_especiales (fecha, hora, evento, detalle, sesion_id) VALUES (?,?,?,?,?)",
                (fecha, hora, EVENTO_CORTE, f"Cambio en caja: {resumen_del_cambio(cambio)}", self.sesion_id),
            )
            # Todo lo que ya existe (incluido el evento de arriba) queda antes del corte.
            cur.execute(
                """
                INSERT INTO cortes_caja (fecha, hora, ultima_venta_id, ultimo_evento_id, sesion_id)
                VALUES (?, ?, (SELECT COALESCE(MAX(id), 0) FROM ventas),
                        (SELECT COALESCE(MAX(id), 0) FROM eventos_especiales), ?)
                """,
                (fecha, hora, self.sesion_id),
            )
            corte_id = cur.lastrowid
            cur.executemany(
                "INSERT INTO cortes_caja_cambio (corte_id, tipo, denominacion, cantidad) VALUES (?,?,?,?)",
                [(corte_id, tipo, denom, cant) for tipo, denom, cant in cambio if cant],
            )
            con.commit()

        return corte_id

    def _ultimo_corte(self, cur, fecha):
        cur.execute(
            """
            SELECT id, hora, ultima_venta_id, ultimo_evento_id FROM cortes_caja
            WHERE fecha = ? ORDER BY id DESC LIMIT 1
            """,
            (fecha,),
        )
        return cur.fetchone()

    def obtener_ventas(self, fecha=None, desde_ultimo_corte=False):
        """Las filas de la tabla de ventas: (hora, producto, precio, cantidad, subtotal).

        Con `desde_ultimo_corte` (la hoja del punto de venta), si ese día hubo un corte de caja
        las filas empiezan con el cambio que se dejó en la caja, una por denominación, seguido
        solo de lo que pasó después del corte. Sin él (revisar un día con VER VENTAS) sale el día
        completo, con el corte como un evento más."""
        fecha = fecha or datetime.now().strftime("%Y-%m-%d")

        with self._connect() as con:
            cur = con.cursor()
            filas = []
            ultima_venta_id = ultimo_evento_id = 0
            corte = self._ultimo_corte(cur, fecha) if desde_ultimo_corte else None
            if corte is not None:
                corte_id, hora_corte, ultima_venta_id, ultimo_evento_id = corte
                cur.execute(
                    "SELECT tipo, denominacion, cantidad FROM cortes_caja_cambio WHERE corte_id = ? ORDER BY id",
                    (corte_id,),
                )
                for tipo, denominacion, cantidad in cur.fetchall():
                    filas.append(
                        (hora_corte, producto_de_cambio(tipo), denominacion, cantidad, denominacion * cantidad)
                    )

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
                    WHERE v.fecha = ? AND v.id > ?

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
                    WHERE e.fecha = ? AND e.id > ?
                )
                ORDER BY hora ASC, tipo_registro ASC, orden_principal ASC, orden_secundario ASC
                """,
                (fecha, ultima_venta_id, fecha, ultimo_evento_id),
            )
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
