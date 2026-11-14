"""Codigos de barras registrados: a que producto pertenecen y a que precio se venden."""

from __future__ import annotations

import sqlite3
import unicodedata
from dataclasses import dataclass

from services.servicio_bd import ServicioBD, ahora_local


@dataclass(frozen=True)
class CodigoBarras:
    id: int
    codigo_barras: str
    producto_id: int
    producto: str
    precio_venta: float
    creado_en: str | None
    otros_codigos: int = 0  # cuantos codigos MAS tiene el mismo producto (solo en el detalle)


class CodigoDuplicado(ValueError):
    """Ya hay otro código registrado con ese texto (sin distinguir mayúsculas)."""


def _sin_acentos(texto):
    normalizado = unicodedata.normalize("NFD", str(texto).lower())
    return "".join(caracter for caracter in normalizado if unicodedata.category(caracter) != "Mn")


_SELECT = """
    SELECT b.id, b.codigo_barras, c.id, c.producto, b.precio_venta, b.creado_en
    FROM codigos_barras_registrados b
    JOIN catalogo_autocompletado c ON c.id = b.producto_id
"""


class CodigosBarrasService(ServicioBD):
    def obtener_codigo_barras_registrado(self, codigo_barras):
        """(producto_id, producto, precio) del codigo, o None si no esta registrado."""
        codigo = str(codigo_barras).strip()
        if not codigo:
            return None

        with self._connect() as con:
            fila = con.execute(_SELECT + " WHERE b.codigo_barras = ?", (codigo,)).fetchone()

        if fila is None:
            return None

        return int(fila[2]), str(fila[3]), float(fila[4])

    def obtener_detalle_codigo_barras(self, codigo_barras):
        """Todo lo que se sabe de un codigo registrado (o None). Sin distinguir mayusculas,
        igual que la columna."""
        codigo = str(codigo_barras).strip()
        if not codigo:
            return None

        with self._connect() as con:
            fila = con.execute(_SELECT + " WHERE b.codigo_barras = ?", (codigo,)).fetchone()
            if fila is None:
                return None
            otros = con.execute(
                "SELECT COUNT(*) FROM codigos_barras_registrados WHERE producto_id = ? AND id <> ?",
                (fila[2], fila[0]),
            ).fetchone()[0]

        return CodigoBarras(
            id=int(fila[0]),
            codigo_barras=str(fila[1]),
            producto_id=int(fila[2]),
            producto=str(fila[3]),
            precio_venta=float(fila[4]),
            creado_en=None if fila[5] is None else str(fila[5]),
            otros_codigos=int(otros),
        )

    def listar_codigos_barras(self, filtro=""):
        """Todos los codigos registrados, ordenados por producto. `filtro` se busca (sin
        distinguir mayusculas ni acentos) en el codigo y en el nombre del producto."""
        with self._connect() as con:
            filas = con.execute(
                _SELECT + " ORDER BY c.producto COLLATE NOCASE ASC, b.codigo_barras COLLATE NOCASE ASC"
            ).fetchall()

        codigos = [
            CodigoBarras(int(f[0]), str(f[1]), int(f[2]), str(f[3]), float(f[4]), None if f[5] is None else str(f[5]))
            for f in filas
        ]

        buscado = _sin_acentos(str(filtro or "").strip())
        if not buscado:
            return codigos

        return [
            codigo
            for codigo in codigos
            if buscado in _sin_acentos(codigo.codigo_barras) or buscado in _sin_acentos(codigo.producto)
        ]

    def registrar_codigo_barras(self, codigo_barras, producto_id, precio_venta):
        codigo = str(codigo_barras).strip()
        if not codigo:
            raise ValueError("El código de barras no puede estar vacío.")

        with self._connect() as con:
            cur = con.cursor()
            cur.execute(
                """
                INSERT INTO codigos_barras_registrados (codigo_barras, producto_id, precio_venta, creado_en, sesion_id)
                VALUES (?,?,?,?,?)
                """,
                (codigo, int(producto_id), float(precio_venta), ahora_local(), self.sesion_id),
            )
            codigo_id = cur.lastrowid
            con.commit()

        return codigo_id

    def registrar_codigos_barras(self, registros):
        """Registra varios códigos de una vez: [(codigo, producto_id, precio), ...]. Todos o
        ninguno: si uno falla (ej. ya estaba registrado), no queda guardado ninguno."""
        filas = []
        for codigo_barras, producto_id, precio_venta in registros:
            codigo = str(codigo_barras).strip()
            if not codigo:
                raise ValueError("El código de barras no puede estar vacío.")
            filas.append((codigo, int(producto_id), float(precio_venta), ahora_local(), self.sesion_id))

        with self._connect() as con:
            con.executemany(
                """
                INSERT INTO codigos_barras_registrados (codigo_barras, producto_id, precio_venta, creado_en, sesion_id)
                VALUES (?,?,?,?,?)
                """,
                filas,
            )
            con.commit()

    def actualizar_codigo_barras(self, codigo_id, codigo_barras, producto_id, precio_venta):
        """Cambia el texto, el producto o el precio de un código registrado. CodigoDuplicado si el
        texto nuevo ya es de otro código. True si existía el código."""
        codigo = str(codigo_barras).strip()
        if not codigo:
            raise ValueError("El código de barras no puede estar vacío.")

        try:
            with self._connect() as con:
                cur = con.cursor()
                cur.execute(
                    """
                    UPDATE codigos_barras_registrados
                    SET codigo_barras = ?, producto_id = ?, precio_venta = ?,
                        actualizado_en = ?, actualizado_sesion_id = ?
                    WHERE id = ?
                    """,
                    (codigo, int(producto_id), float(precio_venta), ahora_local(), self.sesion_id, int(codigo_id)),
                )
                cambios = cur.rowcount
                con.commit()
        except sqlite3.IntegrityError as exc:
            raise CodigoDuplicado(codigo) from exc

        return cambios > 0

    def registrar_impresion(self, codigo_barras, copias, horizontal=False, codificador=None, piezas=None):
        """Deja constancia de que se mandó a imprimir una etiqueta (esté o no registrado el código).
        `copias` son etiquetas; `piezas`, cuántas veces salió el código en total."""
        fecha, hora = ahora_local().split(" ")
        with self._connect() as con:
            cur = con.cursor()
            cur.execute(
                """
                INSERT INTO impresiones_codigos_barras
                    (fecha, hora, codigo_barras, copias, horizontal, codificador, sesion_id, piezas)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    fecha,
                    hora,
                    str(codigo_barras).strip(),
                    int(copias),
                    1 if horizontal else 0,
                    None if codificador is None else str(codificador),
                    self.sesion_id,
                    None if piezas is None else int(piezas),
                ),
            )
            impresion_id = cur.lastrowid
            con.commit()

        return impresion_id
