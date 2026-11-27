"""Genera las etiquetas NIIMBOT de referencia con el código REAL de la v2 (`hardware/barcode_printer.py`
y la librería `niimprint` que usa). No imprime nada.

Guarda `etiquetas_v2.json`:
- `modulos`: el patrón de Code 128 de varios códigos (lo que lee el escáner: debe ser idéntico).
- `pieza` y `etiqueta`: imágenes de la v2 (una pieza con leyenda; la etiqueta vertical de 3 piezas
  con un hueco, ya girada), como renglones de 0/1 (1 = negro). Las barras deben coincidir; el texto
  se dibuja con otro rasterizador (FreeType de PIL vs Rust) y se admite una diferencia mínima.
- `paquetes`: los bytes que la v2 manda a la impresora para esa etiqueta, hablando con una NIIMBOT
  falsa que responde "OK" a todo (el orden y el contenido deben ser idénticos).

Uso (desde v_3/nucleo, con el Python del SISTEMA, donde están niimprint y python-barcode, como en
LibreOffice):  python3 -I pruebas_v2/generar_etiquetas.py [ruta de v_2]
"""

import json
import sys
from pathlib import Path

V2 = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "sistema_ventas" / "v_2"
AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(V2))

import hardware.barcode_printer as bp  # noqa: E402
from niimprint.packet import NiimbotPacket  # noqa: E402

CODIGOS = ["A1B2C3", "123456", "1234AB", "AB1234", "X", "12345", "ñ1"[1:] + "Z9", "abc-.Q"]


def renglones(imagen):
    """La imagen como renglones de '0'/'1' (1 = negro)."""
    img = imagen.convert("L")
    return ["".join("1" if img.getpixel((x, y)) < 128 else "0" for x in range(img.width)) for y in range(img.height)]


class NiimbotFalsa:
    """Transporte que guarda lo enviado y responde "OK" a cada petición, como la B1."""

    def __init__(self):
        self.enviado = bytearray()
        self.respuestas = bytearray()

    def write(self, datos):
        self.enviado.extend(datos)
        tipo = datos[2]
        if tipo == 0x85:  # renglones de la imagen: sin respuesta
            return len(datos)
        if tipo == 0xA3:  # estado de impresión: página 1, progreso 0 y 0 (terminó)
            resp = NiimbotPacket(tipo + 16, b"\x00\x01\x00\x00")
        elif tipo in (0x21, 0x23):  # densidad, tipo de etiqueta
            resp = NiimbotPacket(tipo + 16, b"\x01")
        else:
            resp = NiimbotPacket(tipo + 1, b"\x01")
        self.respuestas.extend(resp.to_bytes())
        return len(datos)

    def read(self, largo):
        datos, self.respuestas = bytes(self.respuestas[:largo]), self.respuestas[largo:]
        return datos


def main():
    bp.time.sleep = lambda s: None  # sin esperas
    casos = {"modulos": {}, "fuente": bp.ImageWriter().font_path}
    for codigo in CODIGOS:
        casos["modulos"][codigo] = bp._crear_generador(codigo, "Code 128").build()[0]

    impresora = bp.BarcodePrinter()
    margenes = (impresora.margen_superior, impresora.margen_derecho, impresora.margen_inferior, impresora.margen_izquierdo)
    casos["margenes"] = list(margenes)
    pieza = bp.dibujar_codigo("A1B2C3", 200, 98, "Code 128", leyenda="15000A1B2C3")
    casos["pieza"] = {"texto": "A1B2C3", "ancho": 200, "alto": 98, "leyenda": "15000A1B2C3", "renglones": renglones(pieza)}
    textos = ["A1B2C3", None, "123456"]
    leyendas = {"A1B2C3": "15000A1B2C3", "123456": "9950123456"}
    etiqueta = bp.componer_vertical(textos, bp.ANCHO_PX, bp.ALTO_PX, "Code 128", margenes, leyendas=leyendas)
    casos["etiqueta"] = {"textos": textos, "leyendas": leyendas, "ancho": etiqueta.width, "alto": etiqueta.height, "renglones": renglones(etiqueta)}

    falsa = NiimbotFalsa()
    cliente = bp.PrinterClientFixed(falsa)
    cliente.print_image(etiqueta, density=1, esperar_final=True)
    casos["paquetes"] = {"densidad": 1, "hex": falsa.enviado.hex()}
    (AQUI / "etiquetas_v2.json").write_text(json.dumps(casos, ensure_ascii=False) + "\n", encoding="utf-8")
    print("etiquetas_v2.json:", len(casos["modulos"]), "códigos;", f"etiqueta {etiqueta.width}x{etiqueta.height};", len(falsa.enviado), "bytes enviados")


if __name__ == "__main__":
    main()
