"""La lista de "Imprimir varios códigos" (sin UNO, para poder probarla): cada renglón es un código
con su producto, su precio y cuántas piezas imprimir; las piezas se acomodan de 3 en 3 por etiqueta."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from dialogs.formato import formatear_precio
from dialogs.parseo import parse_copias, parse_monto
from services.catalogo_service import PREPOSICIONES_CATALOGO, formatear_nombre

PIEZAS_POR_ETIQUETA = 3
MAX_PIEZAS = 99
MAX_LARGO_CODIGO = 6


@dataclass
class Renglon:
    codigo: str
    producto_id: int
    producto: str
    precio: float
    piezas: int
    registrado: bool  # ya estaba en la base; si no, se registra al imprimir


def _plural(cantidad, singular, plural):
    return f"{cantidad} {singular if cantidad == 1 else plural}"


class ListaPiezas:
    def __init__(self):
        self.renglones = []

    def buscar(self, codigo):
        # Sin distinguir mayúsculas, igual que la columna codigo_barras de la base.
        clave = str(codigo).strip().casefold()
        for renglon in self.renglones:
            if renglon.codigo.casefold() == clave:
                return renglon
        return None

    def agregar(self, renglon):
        """Un código que ya está en la lista no se repite: se le suman las piezas."""
        existente = self.buscar(renglon.codigo)
        if existente is None:
            self.renglones.append(renglon)
        else:
            existente.piezas += renglon.piezas

    def quitar(self, indice):
        if 0 <= indice < len(self.renglones):
            del self.renglones[indice]

    @property
    def total_piezas(self):
        return sum(renglon.piezas for renglon in self.renglones)

    @property
    def etiquetas(self):
        return -(-self.total_piezas // PIEZAS_POR_ETIQUETA)

    @property
    def faltantes(self):
        """Piezas que faltan para llenar la última etiqueta (0 si ya está llena)."""
        return -self.total_piezas % PIEZAS_POR_ETIQUETA

    def piezas(self):
        return [(renglon.codigo, renglon.piezas) for renglon in self.renglones]

    def nuevos(self):
        """(codigo, producto_id, precio) de los códigos que hay que registrar."""
        return [(r.codigo, r.producto_id, r.precio) for r in self.renglones if not r.registrado]


def leyenda_con_precio(codigo, precio):
    """Lo que se lee debajo de las barras: el precio en centavos pegado al código, para que el
    precio vaya en la etiqueta sin que se note a simple vista. "ABCDEF" a $100 -> "10000ABCDEF"."""
    return f"{round(float(precio) * 100)}{codigo}"


def textos_renglones(renglones):
    """Un texto por renglón, con cada campo rellenado al más largo de la lista para que los "·"
    queden en columna (la lista del diálogo usa letra de ancho fijo). Precio y piezas se alinean
    por las unidades; "pieza" se rellena a "piezas" para que "(nuevo)" también quede en columna."""
    campos = [
        (r.codigo, formatear_nombre(r.producto), formatear_precio(r.precio), str(r.piezas),
         "pieza" if r.piezas == 1 else "piezas", "" if r.registrado else "(nuevo)")
        for r in renglones
    ]
    if not campos:
        return []
    ancho = [max(len(fila[i]) for fila in campos) for i in range(5)]
    return [
        " · ".join((codigo.ljust(ancho[0]), producto.ljust(ancho[1]), precio.rjust(ancho[2]),
                    f"{piezas.rjust(ancho[3])} {palabra.ljust(ancho[4])}")) + (f" {nuevo}" if nuevo else "")
        for codigo, producto, precio, piezas, palabra, nuevo in campos
    ]


def textos_codigos(codigos):
    """Un texto por CodigoBarras registrado ("código · producto · precio"), en columnas como
    textos_renglones()."""
    campos = [(c.codigo_barras, formatear_nombre(c.producto), formatear_precio(c.precio_venta)) for c in codigos]
    if not campos:
        return []
    ancho = [max(len(fila[i]) for fila in campos) for i in range(3)]
    return [
        " · ".join((codigo.ljust(ancho[0]), producto.ljust(ancho[1]), precio.rjust(ancho[2])))
        for codigo, producto, precio in campos
    ]


def texto_faltantes(faltantes):
    if faltantes == 1:
        return "Falta 1 pieza para llenar la última etiqueta."
    return f"Faltan {faltantes} piezas para llenar la última etiqueta."


def texto_resumen(lista):
    if not lista.renglones:
        return "La lista está vacía."
    resumen = f"Total: {_plural(lista.total_piezas, 'pieza', 'piezas')} en {_plural(lista.etiquetas, 'etiqueta', 'etiquetas')}."
    if lista.faltantes:
        resumen += " " + texto_faltantes(lista.faltantes)
    return resumen


def validar_codigo_escrito(texto, codificador, validar_codigo=None):
    """El código limpio, o ValueError con el motivo."""
    codigo = str(texto).strip()
    if not codigo:
        raise ValueError("Escriba el código.")
    if len(codigo) > MAX_LARGO_CODIGO:
        raise ValueError(f"El código debe tener como máximo {MAX_LARGO_CODIGO} caracteres.")
    if validar_codigo is not None:
        validar_codigo(codigo, codificador)
    return codigo


def leer_piezas(texto):
    try:
        piezas = parse_copias(texto)
    except (TypeError, ValueError):
        raise ValueError(f"Las piezas deben ser un número entero entre 1 y {MAX_PIEZAS}.") from None
    if not 1 <= piezas <= MAX_PIEZAS:
        raise ValueError(f"Las piezas deben estar entre 1 y {MAX_PIEZAS}.")
    return piezas


def leer_precio(texto):
    try:
        precio = parse_monto(texto)
    except ValueError:
        raise ValueError("Escriba el precio de venta (solo números y, si hace falta, punto decimal).") from None
    if precio is None or precio < 0:
        raise ValueError("El precio de venta debe ser mayor o igual a cero.")
    return float(precio)


def _sin_acentos(texto):
    normalizado = unicodedata.normalize("NFD", str(texto).lower())
    return "".join(caracter for caracter in normalizado if unicodedata.category(caracter) != "Mn")


def _iniciales(nombre):
    return "".join(palabra[:1] for palabra in _sin_acentos(nombre).split() if palabra not in PREPOSICIONES_CATALOGO)


def filtrar_productos(productos, texto):
    """Los (id, nombre) cuyo nombre contiene `texto` o empieza con esas iniciales (como el Tab de la
    hoja: "bb" -> "blusa básica"), sin distinguir mayúsculas ni acentos."""
    buscado = _sin_acentos(str(texto).strip())
    if not buscado:
        return list(productos)
    sin_espacios = buscado.replace(" ", "")
    return [
        (producto_id, nombre)
        for producto_id, nombre in productos
        if buscado in _sin_acentos(nombre) or _iniciales(nombre).startswith(sin_espacios)
    ]
