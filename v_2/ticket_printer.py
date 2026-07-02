from __future__ import annotations

from datetime import datetime
from pathlib import Path
import tempfile


try:
    import qrcode
except ImportError:  # pragma: no cover - fallback para entornos sin dependencia
    qrcode = None


class TicketPrinter:
    ESC = 27
    GS = 29
    BUFFER_CHUNK = 4096

    def __init__(self, printer_device="/dev/usb/lp0", website_url="https://fb.com/share/1E14r1SK7f"):
        self.printer_device = printer_device
        self.website_url = website_url
        self.base_dir = Path(__file__).resolve().parent
        self.buffer = bytearray()
        self.reset()

    def reset(self):
        self.buffer = bytearray()
        self.append_byte(self.ESC)
        self.append_byte(64)

    def append_byte(self, value):
        self.buffer.append(int(value) & 0xFF)

    def append_bytes(self, data):
        self.buffer.extend(data)

    def command_print(self, command, value=None):
        self.append_byte(self.ESC)
        self.append_bytes(command.encode("ascii", errors="ignore"))
        if value is not None:
            self.append_byte(value)

    def add_print(self, text):
        self.append_bytes((f"{text}\n").encode("cp850", errors="replace"))

    def add_line_print(self):
        self.add_print("--------------------------------")

    def _candidate_logo_paths(self):
        return [
            self.base_dir / "img" / "logo_buffer.bin",
            self.base_dir.parent / "img" / "logo_buffer.bin",
        ]

    def _load_logo_bytes(self):
        for path in self._candidate_logo_paths():
            if path.exists():
                return path.read_bytes()
        return None

    def add_logo_print(self):
        logo_bytes = self._load_logo_bytes()
        if not logo_bytes:
            return False

        width_bytes = 48
        height = 180
        if len(logo_bytes) % width_bytes == 0:
            height = len(logo_bytes) // width_bytes

        self.append_byte(self.ESC)
        self.append_byte(97)
        self.append_byte(1)

        self.append_byte(self.GS)
        self.append_byte(118)
        self.append_byte(48)
        self.append_byte(0)
        self.append_byte(width_bytes & 0xFF)
        self.append_byte((width_bytes >> 8) & 0xFF)
        self.append_byte(height & 0xFF)
        self.append_byte((height >> 8) & 0xFF)
        self.append_bytes(logo_bytes)

        self.append_byte(self.ESC)
        self.append_byte(97)
        self.append_byte(0)
        return True

    def _qr_bytes(self, text):
        if qrcode is None:
            return None

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=8,
            border=1,
        )
        qr.add_data(text)
        qr.make(fit=True)

        image = qr.make_image(fill_color="black", back_color="white").convert("1")
        width, height = image.size
        width_bytes = (width + 7) // 8

        data = bytearray()
        for y in range(height):
            for byte_index in range(width_bytes):
                byte_value = 0
                for bit_index in range(8):
                    x = byte_index * 8 + bit_index
                    if x < width and image.getpixel((x, y)) == 0:
                        byte_value |= 1 << (7 - bit_index)
                data.append(byte_value)

        return width_bytes, height, bytes(data)

    def add_qr_website_print(self, website_url=None):
        website_url = website_url or self.website_url
        qr_info = self._qr_bytes(website_url)
        if qr_info is None:
            return False

        width_bytes, height, qr_bytes = qr_info

        self.append_byte(self.ESC)
        self.append_byte(97)
        self.append_byte(1)

        self.append_byte(self.GS)
        self.append_byte(118)
        self.append_byte(48)
        self.append_byte(0)
        self.append_byte(width_bytes & 0xFF)
        self.append_byte((width_bytes >> 8) & 0xFF)
        self.append_byte(height & 0xFF)
        self.append_byte((height >> 8) & 0xFF)
        self.append_bytes(qr_bytes)

        self.append_byte(self.ESC)
        self.append_byte(97)
        self.append_byte(0)
        return True

    def _log_error(self, message):
        log_path = self.base_dir / "error_log.txt"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {message}\n")

    def send_print(self):
        ticket_path = Path(tempfile.gettempdir()) / "ticket.bin"
        ticket_path.write_bytes(self.buffer)

        try:
            with open(self.printer_device, "wb") as printer:
                printer.write(self.buffer)
                printer.flush()
        except Exception as exc:
            self._log_error(f"No se pudo imprimir en {self.printer_device}: {exc}")
            return False

        self.reset()
        return True

    def open_cash_drawer(self, m=0, t1=25, t2=250):
        self.reset()
        self.append_byte(self.ESC)
        self.append_byte(112)
        self.append_byte(m)
        self.append_byte(t1)
        self.append_byte(t2)
        return self.send_print()

    def print_sale(self, items, total, recibido, cambio, title="Yaeli's Boutique", website_url=None):
        self.reset()
        self.add_logo_print()
        self.append_byte(10)
        self.append_byte(10)

        self.append_byte(self.ESC)
        self.append_byte(97)
        self.append_byte(1)
        self.add_print(title)
        self.append_byte(self.ESC)
        self.append_byte(97)
        self.append_byte(0)

        self.add_line_print()
        self.add_print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.add_line_print()

        for producto, precio, cantidad, subtotal in items:
            self.add_print(str(producto))
            self.add_print(f"  {int(cantidad)} x ${float(precio):.2f} = ${float(subtotal):.2f}")

        self.add_line_print()
        self.add_print(f"TOTAL: ${float(total):.2f}")
        self.add_print(f"RECIBIDO: ${float(recibido):.2f}")
        self.add_print(f"CAMBIO: ${float(cambio):.2f}")
        self.add_line_print()

        self.append_byte(10)
        self.add_qr_website_print(website_url)
        self.append_byte(10)
        self.append_byte(10)
        return self.send_print()


default_ticket_printer = TicketPrinter()


def imprimir_ticket_venta(items, total, recibido, cambio, title="Yaeli's Boutique", website_url=None):
    return default_ticket_printer.print_sale(items, total, recibido, cambio, title=title, website_url=website_url)