"""Catalogo de productos para el autocompletado (y su busqueda por iniciales)."""

from __future__ import annotations

import re
import sqlite3
import unicodedata

from services.servicio_bd import ServicioBD


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


class ProductoDuplicado(ValueError):
    """Ya hay un producto con ese nombre en el catálogo."""


class ProductoEnUso(ValueError):
    """El producto tiene códigos de barras registrados y no se puede borrar."""


def formatear_nombre(texto):
    """"mayon de faja" -> "Mayon de Faja": capitaliza cada palabra menos las preposiciones."""
    palabras = []
    for palabra in str(texto).strip().split():
        if not palabra:
            continue
        if palabra.lower() in PREPOSICIONES_CATALOGO:
            palabras.append(palabra.lower())
        else:
            palabras.append(palabra[:1].upper() + palabra[1:].lower())
    return " ".join(palabras)


class CatalogoService(ServicioBD):
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

    def normalizar_prefijo(self, texto):
        texto = str(texto).strip().lower()
        if not texto:
            return ""

        normalizado = unicodedata.normalize("NFD", texto)
        sin_acentos = "".join(caracter for caracter in normalizado if unicodedata.category(caracter) != "Mn")
        return "".join(caracter for caracter in sin_acentos if caracter.isalnum())

    def buscar_catalogo_por_iniciales(self, iniciales, limite=20):
        prefijo = self.normalizar_prefijo(iniciales)
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
            raise ValueError("El producto no puede estar vacío.")

        try:
            with self._connect() as con:
                cur = con.cursor()
                cur.execute(
                    "INSERT INTO catalogo_autocompletado (producto) VALUES (?)",
                    (nombre,),
                )
                producto_id = cur.lastrowid
                con.commit()
        except sqlite3.IntegrityError as exc:
            raise ProductoDuplicado(nombre) from exc

        return producto_id

    def editar_producto_autocompletado(self, producto_id, nuevo_nombre):
        nombre = str(nuevo_nombre).strip().lower()
        if not nombre:
            raise ValueError("El producto no puede estar vacío.")

        try:
            with self._connect() as con:
                cur = con.cursor()
                cur.execute(
                    "UPDATE catalogo_autocompletado SET producto = ? WHERE id = ?",
                    (nombre, int(producto_id)),
                )
                cambios = cur.rowcount
                con.commit()
        except sqlite3.IntegrityError as exc:
            raise ProductoDuplicado(nombre) from exc

        return cambios > 0

    def eliminar_producto_autocompletado(self, producto_id):
        try:
            with self._connect() as con:
                cur = con.cursor()
                cur.execute(
                    "DELETE FROM catalogo_autocompletado WHERE id = ?",
                    (int(producto_id),),
                )
                cambios = cur.rowcount
                con.commit()
        except sqlite3.IntegrityError as exc:
            raise ProductoEnUso(str(producto_id)) from exc

        return cambios > 0
