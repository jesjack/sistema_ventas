"""Codigos de barras registrados: a que producto pertenecen y a que precio se venden."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from services.servicio_bd import ServicioBD


@dataclass(frozen=True)
class CodigoBarras:
    id: int
    codigo_barras: str
    producto_id: int
    producto: str
    precio_venta: float
    creado_en: str | None
    otros_codigos: int = 0  # cuantos codigos MAS tiene el mismo producto (solo en el detalle)


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
                "INSERT INTO codigos_barras_registrados (codigo_barras, producto_id, precio_venta) VALUES (?,?,?)",
                (codigo, int(producto_id), float(precio_venta)),
            )
            codigo_id = cur.lastrowid
            con.commit()

        return codigo_id
