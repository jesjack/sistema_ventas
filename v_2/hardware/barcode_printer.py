from __future__ import annotations

from pathlib import Path
import struct
import tempfile
import threading
import time
import traceback

from PIL import Image
from barcode import Code128
from barcode.writer import ImageWriter
from niimprint import SerialTransport, PrinterClient
from niimprint.packet import NiimbotPacket

try:
    from serial.tools import list_ports
except ImportError:  # pragma: no cover - fallback if pyserial is unavailable
    list_ports = None

RESAMPLING = getattr(Image, "Resampling", Image)

ANCHO_PX = 400
ALTO_PX = 224
ROTAR_90 = True
MARGEN_SUPERIOR = 16  # aprox. 2 mm a 203 dpi

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


def generar_codigo_barras_code128(texto, ancho_maximo, alto_maximo):
    generador = Code128(texto, writer=ImageWriter())
    imagen = generador.render(
        writer_options={
            "module_width": 0.25,
            "module_height": 14.0,
            "quiet_zone": 2.0,
            "font_size": 10,
            "text_distance": 2,
            "write_text": True,
            "background": "white",
            "foreground": "black",
            "dpi": 203,
        }
    )

    if imagen.width > ancho_maximo or imagen.height > alto_maximo:
        escala = min(ancho_maximo / imagen.width, alto_maximo / imagen.height)
        nuevo_tamano = (
            max(1, int(imagen.width * escala)),
            max(1, int(imagen.height * escala)),
        )
        imagen = imagen.resize(nuevo_tamano, RESAMPLING.LANCZOS)

    canvas = Image.new("L", (ancho_maximo, alto_maximo), color=255)
    offset_x = max(0, (ancho_maximo - imagen.width) // 2)
    offset_y = max(0, (alto_maximo - imagen.height) // 2)
    canvas.paste(imagen.convert("L"), (offset_x, offset_y))
    return canvas


def ajustar_codigo_barras(imagen, ancho, alto, rotar_90=False, margen_superior=0):
    if rotar_90:
        imagen = imagen.rotate(90, expand=True)

    mascara = Image.eval(imagen, lambda pixel: 255 - pixel)
    bbox = mascara.getbbox()
    if bbox:
        imagen = imagen.crop(bbox)

    alto_util = max(1, alto - margen_superior)
    imagen = imagen.resize((ancho, alto_util), RESAMPLING.NEAREST)

    canvas = Image.new("L", (ancho, alto), color=255)
    canvas.paste(imagen, (0, margen_superior))
    return canvas


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
    def __init__(self, ancho_px=ANCHO_PX, alto_px=ALTO_PX, rotar_90=ROTAR_90, margen_superior=MARGEN_SUPERIOR, puerto_impresora="auto"):
        self.ancho_px = ancho_px
        self.alto_px = alto_px
        self.rotar_90 = rotar_90
        self.margen_superior = margen_superior
        self.puerto_impresora = puerto_impresora
        self.base_dir = Path(__file__).resolve().parent
        self.ruta_imagen = self.base_dir / "etiqueta_usb.png"

    def _crear_imagen(self, texto_codigo):
        imagen_barra = generar_codigo_barras_code128(
            texto_codigo,
            self.ancho_px - 24,
            self.alto_px - 24,
        )
        return ajustar_codigo_barras(
            imagen_barra,
            self.ancho_px,
            self.alto_px,
            rotar_90=self.rotar_90,
            margen_superior=self.margen_superior,
        )

    def _imprimir_codigo_barras_bloqueante(self, texto_codigo, numero_copias=1, density=1):
        imagen = self._crear_imagen(texto_codigo)
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

    def imprimir_codigo_barras(self, texto_codigo, numero_copias=1, density=1, en_segundo_plano=True):
        if not en_segundo_plano:
            return self._imprimir_codigo_barras_bloqueante(texto_codigo, numero_copias=numero_copias, density=density)

        def trabajo():
            try:
                self._imprimir_codigo_barras_bloqueante(
                    texto_codigo,
                    numero_copias=numero_copias,
                    density=density,
                )
            except Exception:
                traceback.print_exc()

        hilo = threading.Thread(target=trabajo, daemon=True)
        hilo.start()
        return hilo


_default_barcode_printer = BarcodePrinter()


def imprimir_codigo_barras(texto_codigo, numero_copias=1, density=1, en_segundo_plano=True):
    return _default_barcode_printer.imprimir_codigo_barras(
        texto_codigo,
        numero_copias=numero_copias,
        density=density,
        en_segundo_plano=en_segundo_plano,
    )


if __name__ == "__main__":
    imprimir_codigo_barras("Hello world", numero_copias=3, density=1)