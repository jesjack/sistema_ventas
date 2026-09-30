from __future__ import annotations

from pathlib import Path
import struct
import tempfile
import threading
import time
import traceback

from PIL import Image, ImageDraw, ImageFont
from barcode import get_barcode_class
from barcode.writer import ImageWriter
from niimprint import SerialTransport, PrinterClient
from niimprint.packet import NiimbotPacket

try:
    from serial.tools import list_ports
except ImportError:  # pragma: no cover - fallback if pyserial is unavailable
    list_ports = None


# El cabezal de la B1 imprime 384 px (48 mm): con 400 px se perdían 8 px de cada lado, medido con la
# prueba de márgenes el 2026-09-29.
ANCHO_PX = 384
ALTO_PX = 224
ROTAR_90 = True
PX_POR_MM = 8  # 203 dpi
# La impresión arranca ~1-1.5 mm antes del borde superior de la etiqueta (misma prueba); abajo
# sobran ~2 mm en blanco, así que ahí no hace falta margen.
MARGEN_SUPERIOR = 3 * PX_POR_MM
# Lado izquierdo de la imagen: en horizontal es la izquierda del código y en vertical (girado 90°
# a la izquierda) es donde queda el inicio de las barras, o sea "arriba" al leerlo derecho.
MARGEN_IZQUIERDO = 3 * PX_POR_MM
# En vertical aquí queda el texto del código, que antes salía mordido por el recorte.
MARGEN_DERECHO = 2 * PX_POR_MM
MARGEN_INFERIOR = 0

TAMANO_TEXTO_PX = 18  # cifras de ~1.6 mm de alto
SEPARACION_TEXTO_PX = 3  # entre las barras y el texto
# En vertical la etiqueta sale con varias copias del código para recortarlas con tijeras.
PARTES_VERTICAL = 3
SEPARACION_PARTES_PX = 3 * PX_POR_MM

# Nombre para el diálogo -> clase de python-barcode y opciones. Solo los que aceptan códigos
# cortos (máx. 6 caracteres) y que el lector devuelve tal cual se escribieron.
CODIFICADORES = {
    "Code 128": ("code128", {}),
    # Sin dígito verificador: la mayoría de los lectores lo transmitirían pegado al código.
    "Code 39": ("code39", {"add_checksum": False}),
    "ITF (solo números)": ("itf", {}),
}
CODIFICADOR_PREDETERMINADO = "Code 128"

_PRINT_LOCK = threading.Lock()


def resolver_puerto_impresora(preferido="auto"):
    if preferido and preferido != "auto":
        return preferido

    if list_ports is None:
        return preferido

    puertos = list(list_ports.comports())
    candidatos = []

    for puerto in puertos:
        descripcion = f"{puerto.description} {puerto.manufacturer} {puerto.product}"
        if puerto.device == "/dev/ttyACM0":
            return puerto.device
        if "B1 LABEL PRINTER" in descripcion or (puerto.vid == 0x3513 and puerto.pid == 0x0002):
            candidatos.append(puerto.device)

    if len(candidatos) == 1:
        return candidatos[0]

    if len(puertos) == 1:
        return puertos[0].device

    if candidatos:
        return candidatos[0]

    return preferido


def _crear_generador(texto, codificador):
    try:
        nombre, opciones = CODIFICADORES[codificador]
    except KeyError:
        raise ValueError(f"Codificador desconocido: {codificador}") from None
    if nombre == "itf" and not texto.isdigit():
        raise ValueError("ITF solo acepta números.")
    if nombre == "itf" and len(texto) % 2:
        # python-barcode le pondría un 0 al inicio y el lector leería otro código.
        raise ValueError("ITF necesita una cantidad par de dígitos.")
    try:
        return get_barcode_class(nombre)(texto, writer=ImageWriter(), **opciones)
    except Exception as exc:  # IllegalCharacterError, NumberOfDigitsError, ...
        raise ValueError(f"{codificador} no acepta el código '{texto}': {exc}") from exc


def validar_codigo(texto, codificador=CODIFICADOR_PREDETERMINADO):
    """Lanza ValueError (con el motivo en español) si el codificador no acepta el texto."""
    _crear_generador(texto, codificador)


def _fuente(tamano):
    # La que trae python-barcode: así no depende de las fuentes instaladas (Linux o Windows).
    return ImageFont.truetype(ImageWriter().font_path, tamano)


def dibujar_codigo(texto, ancho, alto, codificador=CODIFICADOR_PREDETERMINADO):
    """Barras y, debajo, el texto del código, en exactamente ancho x alto px, en blanco y negro puro.

    Las barras se dibujan desde el patrón de módulos y no escalando una imagen ya hecha: así cada
    módulo mide lo mismo (o casi) y el texto no queda estirado ni encimado sobre las barras."""
    generador = _crear_generador(texto, codificador)
    modulos = generador.build()[0]
    leyenda = generador.get_fullcode()

    imagen = Image.new("L", (ancho, alto), color=255)
    dibujo = ImageDraw.Draw(imagen)
    dibujo.fontmode = "1"  # sin antialias: la térmica solo imprime negro o blanco

    tamano = TAMANO_TEXTO_PX
    fuente = _fuente(tamano)
    while tamano > 8 and dibujo.textlength(leyenda, font=fuente) > ancho:
        tamano -= 1
        fuente = _fuente(tamano)
    izq, arriba, der, abajo = dibujo.textbbox((0, 0), leyenda, font=fuente)
    alto_texto = abajo - arriba
    alto_barras = max(1, alto - alto_texto - SEPARACION_TEXTO_PX)

    # Módulos de ancho entero (mínimo 2 px) para que todas las barras del mismo grosor salgan
    # idénticas; lo que sobra queda como zona blanca a los lados, que también ayuda al lector. Si ni
    # así caben, se reparte el ancho entre los módulos (algunos salen 1 px más anchos que otros).
    entero = ancho // len(modulos)
    paso = entero if entero >= 2 else ancho / len(modulos)
    inicio = (ancho - paso * len(modulos)) / 2
    for indice, modulo in enumerate(modulos):
        if modulo == "1":
            x0 = round(inicio + indice * paso)
            x1 = round(inicio + (indice + 1) * paso)
            dibujo.rectangle((x0, 0, x1 - 1, alto_barras - 1), fill=0)

    x_texto = (ancho - (der - izq)) / 2 - izq
    dibujo.text((x_texto, alto - alto_texto - arriba), leyenda, fill=0, font=fuente)
    return imagen


def linea_punteada(dibujo, x0, y0, x1, y1, trazo=6, hueco=4):
    """Línea horizontal o vertical punteada (guía para recortar con tijeras)."""
    if y0 == y1:
        for x in range(x0, x1, trazo + hueco):
            dibujo.line((x, y0, min(x + trazo - 1, x1), y0), fill=0, width=2)
    else:
        for y in range(y0, y1, trazo + hueco):
            dibujo.line((x0, y, x0, min(y + trazo - 1, y1)), fill=0, width=2)


def componer_vertical(texto, ancho, alto, codificador, margenes, partes=PARTES_VERTICAL,
                      separacion=SEPARACION_PARTES_PX):
    """La etiqueta en vertical: `partes` copias del código apiladas a lo largo de la etiqueta, con
    una línea punteada en medio de cada separación para recortarlas. Se arma "derecha" (el código
    leyéndose de izquierda a derecha, texto abajo) y al final se gira 90° a la izquierda; por eso
    los márgenes de la imagen se reacomodan: su izquierda es la parte de arriba de la etiqueta
    derecha, su derecha es la de abajo, su parte de abajo es la izquierda y su parte de arriba es
    la derecha."""
    m_arriba, m_derecho, m_abajo, m_izquierdo = margenes
    ancho_d, alto_d = alto, ancho  # medidas de la etiqueta vista derecha
    arriba_d, abajo_d, izquierda_d, derecha_d = m_izquierdo, m_derecho, m_abajo, m_arriba

    ancho_util = ancho_d - izquierda_d - derecha_d
    alto_util = alto_d - arriba_d - abajo_d
    alto_parte = (alto_util - separacion * (partes - 1)) // partes
    pieza = dibujar_codigo(texto, ancho_util, alto_parte, codificador)

    lienzo = Image.new("L", (ancho_d, alto_d), color=255)
    dibujo = ImageDraw.Draw(lienzo)
    for indice in range(partes):
        y = arriba_d + indice * (alto_parte + separacion)
        lienzo.paste(pieza, (izquierda_d, y))
        if indice:
            # De borde a borde, para que se vea por dónde cortar aunque la etiqueta se mueva un poco.
            linea_punteada(dibujo, 0, y - separacion // 2, ancho_d - 1, y - separacion // 2)
    return lienzo.rotate(90, expand=True)


def componer_horizontal(texto, ancho, alto, codificador, margenes):
    m_arriba, m_derecho, m_abajo, m_izquierdo = margenes
    pieza = dibujar_codigo(texto, ancho - m_izquierdo - m_derecho, alto - m_arriba - m_abajo, codificador)
    lienzo = Image.new("L", (ancho, alto), color=255)
    lienzo.paste(pieza, (m_izquierdo, m_arriba))
    return lienzo


def generar_etiqueta_prueba(ancho=ANCHO_PX, alto=ALTO_PX):
    """Un marco pegado al borde de la imagen, con marcas cada 1 mm (más largas cada 5 mm) hacia
    adentro. Al imprimirla se ve qué lado se corta y cuántos mm hay que dejar de margen. Los
    letreros están derechos con la etiqueta en horizontal."""
    imagen = Image.new("L", (ancho, alto), color=255)
    dibujo = ImageDraw.Draw(imagen)
    dibujo.rectangle((0, 0, ancho - 1, alto - 1), outline=0, width=2)

    for mm in range(1, 11):
        paso = mm * PX_POR_MM
        largo = 14 if mm % 5 == 0 else 7
        dibujo.line((paso, 0, paso, largo), fill=0, width=2)  # arriba, desde la izquierda
        dibujo.line((paso, alto - 1 - largo, paso, alto - 1), fill=0)  # abajo
        dibujo.line((ancho - 1 - paso, 0, ancho - 1 - paso, largo), fill=0)  # arriba, desde la derecha
        dibujo.line((0, paso, largo, paso), fill=0, width=2)  # izquierda
        dibujo.line((ancho - 1 - largo, paso, ancho - 1, paso), fill=0)  # derecha

    dibujo.text((ancho // 2, 20), "ARRIBA", fill=0, anchor="mt")
    dibujo.text((ancho // 2, alto - 20), "ABAJO", fill=0, anchor="mb")
    dibujo.text((20, alto // 2), "IZQ.", fill=0, anchor="lm")
    dibujo.text((ancho - 20, alto // 2), "DER.", fill=0, anchor="rm")
    dibujo.text((ancho // 2, alto // 2), "Marcas cada 1 mm", fill=0, anchor="mm")
    return imagen


class PrinterClientFixed(PrinterClient):
    def _wait_for_print_finish(self, timeout=15.0, interval=0.1):
        deadline = time.monotonic() + timeout
        last_status = None

        while time.monotonic() < deadline:
            try:
                status = self.get_print_status()
                last_status = status
                if status.get("progress1", 0) == 0 and status.get("progress2", 0) == 0:
                    return status
            except Exception:
                pass
            time.sleep(interval)

        return last_status

    def print_image(self, image, density=1, esperar_final=True):
        self._send(NiimbotPacket(0x54, b"\x01"))
        time.sleep(0.05)
        try:
            self._recv()
        except Exception:
            pass

        self.set_label_density(density)
        self.set_label_type(1)

        self._send(NiimbotPacket(0x01, b"\x00\x01\x00\x00\x00\x00\x00"))
        time.sleep(0.1)
        try:
            self._recv()
        except Exception:
            pass

        self.start_page_print()

        height, width = image.height, image.width
        self._send(NiimbotPacket(0x13, struct.pack(">HHH", height, width, 1)))
        time.sleep(0.1)
        try:
            self._recv()
        except Exception:
            pass

        for pkt in self._encode_image(image):
            self._send(pkt)

        self.end_page_print()
        if esperar_final:
            self._wait_for_print_finish(timeout=15.0, interval=0.1)
            while not self.end_print():
                time.sleep(0.1)


class BarcodePrinter:
    def __init__(self, ancho_px=ANCHO_PX, alto_px=ALTO_PX, rotar_90=ROTAR_90, margen_superior=MARGEN_SUPERIOR,
                 margen_izquierdo=MARGEN_IZQUIERDO, margen_derecho=MARGEN_DERECHO,
                 margen_inferior=MARGEN_INFERIOR, puerto_impresora="auto"):
        self.ancho_px = ancho_px
        self.alto_px = alto_px
        self.rotar_90 = rotar_90
        self.margen_superior = margen_superior
        self.margen_izquierdo = margen_izquierdo
        self.margen_derecho = margen_derecho
        self.margen_inferior = margen_inferior
        self.puerto_impresora = puerto_impresora
        self.base_dir = Path(__file__).resolve().parent
        self.ruta_imagen = self.base_dir / "etiqueta_usb.png"

    def _crear_imagen(self, texto_codigo, horizontal=False, codificador=CODIFICADOR_PREDETERMINADO):
        margenes = (self.margen_superior, self.margen_derecho, self.margen_inferior, self.margen_izquierdo)
        if horizontal or not self.rotar_90:
            return componer_horizontal(texto_codigo, self.ancho_px, self.alto_px, codificador, margenes)
        return componer_vertical(texto_codigo, self.ancho_px, self.alto_px, codificador, margenes)

    def _imprimir_codigo_barras_bloqueante(self, texto_codigo, numero_copias=1, density=1, horizontal=False,
                                           codificador=CODIFICADOR_PREDETERMINADO):
        imagen = self._crear_imagen(texto_codigo, horizontal=horizontal, codificador=codificador)
        return self._imprimir_imagen_bloqueante(imagen, numero_copias=numero_copias, density=density)

    def _imprimir_imagen_bloqueante(self, imagen, numero_copias=1, density=1):
        imagen.save(self.ruta_imagen)

        with _PRINT_LOCK:
            puerto = resolver_puerto_impresora(self.puerto_impresora)
            transporte = SerialTransport(port=puerto)
            cliente = PrinterClientFixed(transporte)

            with Image.open(self.ruta_imagen) as img:
                total_copias = max(1, int(numero_copias))
                for indice in range(total_copias):
                    cliente.print_image(img, density=density, esperar_final=(indice == total_copias - 1))

        return True

    def imprimir_codigo_barras(self, texto_codigo, numero_copias=1, density=1, en_segundo_plano=True, horizontal=False,
                               codificador=CODIFICADOR_PREDETERMINADO):
        # Se valida aquí (y no en el hilo) para que un código inválido llegue como error a quien imprime.
        validar_codigo(texto_codigo, codificador)
        return self._lanzar(
            self._imprimir_codigo_barras_bloqueante,
            en_segundo_plano,
            texto_codigo,
            numero_copias=numero_copias,
            density=density,
            horizontal=horizontal,
            codificador=codificador,
        )

    def imprimir_etiqueta_prueba(self, density=1, en_segundo_plano=True):
        imagen = generar_etiqueta_prueba(self.ancho_px, self.alto_px)
        return self._lanzar(self._imprimir_imagen_bloqueante, en_segundo_plano, imagen, density=density)

    @staticmethod
    def _lanzar(funcion, en_segundo_plano, *args, **kwargs):
        if not en_segundo_plano:
            return funcion(*args, **kwargs)

        def trabajo():
            try:
                funcion(*args, **kwargs)
            except Exception:
                traceback.print_exc()

        hilo = threading.Thread(target=trabajo, daemon=True)
        hilo.start()
        return hilo


_default_barcode_printer = BarcodePrinter()


def imprimir_codigo_barras(texto_codigo, numero_copias=1, density=1, en_segundo_plano=True, horizontal=False,
                           codificador=CODIFICADOR_PREDETERMINADO):
    return _default_barcode_printer.imprimir_codigo_barras(
        texto_codigo,
        numero_copias=numero_copias,
        density=density,
        en_segundo_plano=en_segundo_plano,
        horizontal=horizontal,
        codificador=codificador,
    )


def imprimir_etiqueta_prueba(density=1, en_segundo_plano=True):
    return _default_barcode_printer.imprimir_etiqueta_prueba(density=density, en_segundo_plano=en_segundo_plano)


if __name__ == "__main__":
    imprimir_codigo_barras("Hello world", numero_copias=3, density=1)