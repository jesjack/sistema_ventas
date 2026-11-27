"""Genera los tickets ESC/POS de referencia con el código REAL de la v2 (`hardware/ticket_printer.py`).

No imprime nada: `send_print` devuelve los bytes en vez de escribirlos a la impresora. La fecha es
fija, el logo es uno de prueba y el QR se hace de una URL de prueba. Las tres líneas del encabezado
de la tienda (dirección y RFC, escritas en el código de la v2) se cambian por unas INVENTADAS
mientras se genera: el repositorio es público y esos datos no deben copiarse aquí.

Guarda `tickets_v2.json`: cada caso con sus entradas y los bytes (hex). Las pruebas de Rust
(`ticket.rs`) arman los mismos tickets y comparan byte por byte.

Uso (desde v_3/nucleo):  python3 -I pruebas_v2/generar_tickets.py [ruta de v_2]
(El Python del SISTEMA: es el de LibreOffice, donde imprime la v2, y el que tiene `qrcode`; el venv de
la v2 no lo tiene.)
"""

import json
import sys
from datetime import datetime
from pathlib import Path

V2 = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "sistema_ventas" / "v_2"
AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(V2))

import hardware.ticket_printer as tp  # noqa: E402

ENCABEZADO_DE_PRUEBA = ["Calle Falsa No. 123", "Centro C.P. 00000", "RFC: XAXX010101000"]
URL_DE_PRUEBA = "https://example.com/tienda"
# Un logo de prueba: 48 bytes de ancho (384 puntos) por 4 renglones, con un patrón reconocible.
LOGO_DE_PRUEBA = bytes((i * 7) % 256 for i in range(48 * 4))
FECHA = datetime(2026, 11, 26, 17, 44, 3)


class FechaFija(datetime):
    @classmethod
    def now(cls, tz=None):
        return FECHA


def impresora():
    p = tp.TicketPrinter(printer_device="/dev/null", website_url=URL_DE_PRUEBA)
    p.send_print = lambda: bytes(p.buffer)  # no imprime: devuelve lo que mandaría
    p._load_logo_bytes = lambda: LOGO_DE_PRUEBA
    # Las líneas del encabezado son las tres primeras que se escriben en un ticket de venta.
    original = p.add_print
    estado = {"n": 0, "en_venta": False}

    def add_print(texto):
        if estado["en_venta"] and estado["n"] < len(ENCABEZADO_DE_PRUEBA):
            texto = ENCABEZADO_DE_PRUEBA[estado["n"]]
            estado["n"] += 1
        return original(texto)

    p.add_print = add_print
    return p, estado


def venta(items, total, recibido, cambio):
    p, estado = impresora()
    estado["en_venta"] = True
    return p.print_sale(items, total, recibido, cambio)


def qr_de_prueba():
    """El bitmap del QR como lo arma la v2 (la v3 lo recibe ya hecho, en la configuración)."""
    p, _ = impresora()
    ancho_bytes, alto, datos = p._qr_bytes(URL_DE_PRUEBA)
    return {"ancho_bytes": ancho_bytes, "alto": alto, "hex": datos.hex()}


def main():
    tp.datetime = FechaFija
    casos = {
        "encabezado": ENCABEZADO_DE_PRUEBA,
        "logo_hex": LOGO_DE_PRUEBA.hex(),
        "qr": qr_de_prueba(),
        "ventas": [],
        "cortes": [],
    }
    for items, total, recibido, cambio in [
        ([("blusa básica", 150.0, 2, 300.0)], 300.0, 500.0, 200.0),
        ([("Niño ñandú pantalón", 99.5, 1, 99.5), ("conjunto", 250.0, 1, 250.0), ("devolución", -150.0, 1, -150.0)], 199.5, 199.5, 0.0),
        ([("café € ü «x»", 12.0, 3, 36.0)], 36.0, 100.0, 64.0),
    ]:
        casos["ventas"].append({
            "items": [list(i) for i in items], "total": total, "recibido": recibido, "cambio": cambio,
            "hex": venta(items, total, recibido, cambio).hex(),
        })
    for cambio, usuario in [
        ([("BILLETE", 500.0, 2), ("BILLETE", 20.0, 0), ("MONEDA", 1.0, 35)], "nancy"),
        ([("BILLETE", 200.0, 1)], None),
    ]:
        p, _ = impresora()
        casos["cortes"].append({"cambio": [list(c) for c in cambio], "usuario": usuario, "hex": p.print_cash_cut(cambio, usuario=usuario).hex()})
    p, _ = impresora()
    casos["cajon_hex"] = p.open_cash_drawer().hex()
    (AQUI / "tickets_v2.json").write_text(json.dumps(casos, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("tickets_v2.json:", len(casos["ventas"]), "ventas,", len(casos["cortes"]), "cortes, cajón")


if __name__ == "__main__":
    main()
