from PIL import Image, ImageDraw
from niimprint import SerialTransport, PrinterClient
from niimprint.packet import NiimbotPacket
import os
import struct
import time

from barcode import Code128
from barcode.writer import ImageWriter

try:
    from serial.tools import list_ports
except ImportError:  # pragma: no cover - fallback if pyserial is unavailable
    list_ports = None

RESAMPLING = getattr(Image, "Resampling", Image)

# Obtener la ruta absoluta del directorio donde está ESTE script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ruta_imagen = os.path.join(BASE_DIR, "etiqueta_usb.png")

# Para una etiqueta de 50x30mm en una B1 de 203 dpi, el alto util real suele quedar mas cerca de 224 px.
ANCHO_PX = 400
ALTO_PX = 224
ROTAR_90 = False # nota, no mover esto, la impresora no es compatible así
MARGEN_SUPERIOR = 16  # aprox. 2 mm a 203 dpi


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

    def print_image(self, image, density=1):
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
        self._wait_for_print_finish(timeout=1.0, interval=0.1)
        while not self.end_print():
            time.sleep(0.1)


# 1. Crear la imagen con un solo código de barras vertical
anchura, altura = ANCHO_PX, ALTO_PX
imagen = Image.new("L", (anchura, altura), color=255)
texto_barra = "c v"
imagen_barra = generar_codigo_barras_code128(texto_barra, anchura - 24, altura - 24)
imagen = ajustar_codigo_barras(imagen_barra, anchura, altura, rotar_90=True, margen_superior=MARGEN_SUPERIOR)

# Guardar con ruta absoluta garantizada
imagen.save(ruta_imagen)

# # 2. Configurar la conexión USB (Serial)
# puerto_usb = "COM4" 

try:
    puerto = resolver_puerto_impresora("auto")
    transporte = SerialTransport(port=puerto)
    cliente = PrinterClientFixed(transporte)

    
    print("Enviando datos a la Niimbot B1 por USB...")
    
    # Abrimos la imagen explícitamente y la pasamos a la librería.
    with Image.open(ruta_imagen) as img:
        cliente.print_image(img, density=1)
        
    print("¡Impresión completada con éxito!")

except Exception as e:
    print(f"Error al conectar o imprimir: {e}")
