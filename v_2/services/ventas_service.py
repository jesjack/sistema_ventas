"""Ventas, eventos especiales del historial y codigos de autorizacion."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from services.servicio_bd import ServicioBD


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
