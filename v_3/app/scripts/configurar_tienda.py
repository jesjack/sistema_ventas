"""Crea datos/tienda.json (los datos de la tienda que lleva el ticket) a partir de la v2.

El ticket de la v2 tiene en su CÓDIGO la dirección, el RFC, el nombre y la URL del QR, y el logo en
un archivo. Este script los EXTRAE ejecutando la v2 (no los copia al repositorio, que es público):
captura las líneas del encabezado mientras la v2 arma un ticket que no se imprime, lee su logo y
genera el QR con su mismo código. tienda.json está en datos/ (fuera de git). En producción, va junto
a la base de la v3.

Uso (desde v_3/app, con el Python del SISTEMA, que tiene `qrcode` como el de LibreOffice):
    python3 -I scripts/configurar_tienda.py [ruta de v_2] [destino]
"""

import inspect
import json
import sys
from pathlib import Path

V2 = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "sistema_ventas" / "v_2"
DESTINO = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parent.parent / "datos" / "tienda.json"
sys.path.insert(0, str(V2))

import hardware.ticket_printer as tp  # noqa: E402


def main() -> None:
    p = tp.TicketPrinter(printer_device="/dev/null")
    p.send_print = lambda: True  # nunca imprime
    lineas: list[str] = []
    original = p.add_print
    p.add_print = lambda texto: (lineas.append(str(texto)), original(texto))[1]
    p.print_sale([], 0, 0, 0)
    encabezado = lineas[: lineas.index("")]  # hasta el renglón vacío antes de la fecha
    qr = p._qr_bytes(p.website_url)
    if qr is None:
        sys.exit("No se pudo generar el QR (¿falta `qrcode`? Usa el Python del sistema).")
    ancho_bytes, alto, datos = qr
    logo = p._load_logo_bytes()
    tienda = {
        "nombre": inspect.signature(tp.TicketPrinter.print_cash_cut).parameters["title"].default,
        "encabezado": encabezado,
        "logo_hex": logo.hex() if logo else None,
        "qr": {"ancho_bytes": ancho_bytes, "alto": alto, "hex": datos.hex()},
    }
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text(json.dumps(tienda, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{DESTINO}: {len(encabezado)} líneas de encabezado, logo {len(logo or b'')} bytes, QR {ancho_bytes}x{alto}")


if __name__ == "__main__":
    main()
