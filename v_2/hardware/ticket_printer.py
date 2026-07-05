from __future__ import annotations

from datetime import datetime
from pathlib import Path
import tempfile
import os
import glob
import platform
import shutil
import subprocess


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
        self.base_dir = Path(__file__).resolve().parent.parent
        self.logs_dir = self.base_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
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
        log_path = self.logs_dir / "error_log.txt"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {message}\n")

    def find_printer_device(self):
        """Try to locate a usable printer device.

        Returns:
            str | None: Path to device or special Windows marker 'win32:PRINTER_NAME'.
        """
        # If current device already exists as a file, use it
        try:
            # If it's a Windows marker already, return it
            if isinstance(self.printer_device, str) and self.printer_device.startswith("win32:"):
                return self.printer_device

            path = Path(self.printer_device)
            if path.exists():
                return str(path)
        except Exception:
            pass

        # Windows: try to use the default or first available printer via win32print
        if os.name == "nt":
            try:
                import win32print  # type: ignore

                try:
                    default = win32print.GetDefaultPrinter()
                except Exception:
                    default = None

                if default:
                    return f"win32:{default}"

                # enumerate printers and return first
                printers = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)
                if printers:
                    # printers entries are tuples where name usually is element 2 or 2 depending on platform
                    name = printers[0][2] if len(printers[0]) > 2 else printers[0][0]
                    return f"win32:{name}"
            except Exception:
                # win32print not available or failed
                return None

        # POSIX / Linux: search common device locations first (prefer direct device)
        candidates = []
        # common USB/serial device globs
        candidates.extend(glob.glob('/dev/usb/lp*'))
        candidates.extend(glob.glob('/dev/ttyUSB*'))
        candidates.extend(glob.glob('/dev/ttyACM*'))
        candidates.extend(glob.glob('/dev/serial/by-id/*'))
        candidates.extend(glob.glob('/dev/pts/*'))
        candidates.extend(glob.glob('/dev/lp*'))

        # Add some common exact paths
        candidates.extend(['/dev/usb/lp0', '/dev/lp0', '/dev/parallel0'])

        for p in candidates:
            try:
                if Path(p).exists():
                    return p
            except Exception:
                continue

        # If no direct device found, try CUPS (lp/lpr) if available
        try:
            if shutil.which('lp') or shutil.which('lpr'):
                # try to get default printer name via lpstat
                try:
                    out = subprocess.check_output(['lpstat', '-d'], stderr=subprocess.DEVNULL, text=True)
                    # expected: "system default destination: PRINTER_NAME"
                    if ':' in out:
                        name = out.strip().split(':', 1)[1].strip()
                        if name:
                            return f"cups:{name}"
                except Exception:
                    # fallback marker indicating use of lp/lpr without specific name
                    return 'cups:default'
        except Exception:
            pass

        return None

    def send_print(self):
        # Save a copy for debugging
        ticket_path = Path(tempfile.gettempdir()) / "ticket.bin"
        ticket_path.write_bytes(self.buffer)

        device = self.find_printer_device() or self.printer_device

        # Windows raw printing using win32print when device is a win32 marker
        if isinstance(device, str) and device.startswith("win32:") and os.name == "nt":
            try:
                import win32print  # type: ignore

                printer_name = device.split(":", 1)[1]
                hPrinter = win32print.OpenPrinter(printer_name)
                try:
                    # Doc info: (name, outputfile, datatype)
                    doc = ("Ticket", None, "RAW")
                    win32print.StartDocPrinter(hPrinter, 1, doc)
                    win32print.StartPagePrinter(hPrinter)
                    win32print.WritePrinter(hPrinter, bytes(self.buffer))
                    win32print.EndPagePrinter(hPrinter)
                    win32print.EndDocPrinter(hPrinter)
                finally:
                    win32print.ClosePrinter(hPrinter)
            except Exception as exc:
                self._log_error(f"No se pudo imprimir en '{device}': {exc}")
                return False

            self.reset()
            return True
        # CUPS / lp/lpr fallback for Linux/Unix when device is 'cups:' marker
        if isinstance(device, str) and device.startswith('cups:'):
            # Avoid evaluating platform in the outer condition (Pylance may statically evaluate it).
            if os.name == 'nt':
                self._log_error('CUPS printing requested but running on Windows')
                return False
            
            try:
                printer_name = device.split(":", 1)[1]
                # Use the saved temp file and call lp/lpr
                if printer_name and printer_name not in ('', 'default'):
                    if shutil.which('lp'):
                        cmd = ['lp', '-d', printer_name, str(ticket_path)]
                    elif shutil.which('lpr'):
                        cmd = ['lpr', '-P', printer_name, str(ticket_path)]
                    else:
                        cmd = None
                else:
                    if shutil.which('lp'):
                        cmd = ['lp', str(ticket_path)]
                    elif shutil.which('lpr'):
                        cmd = ['lpr', str(ticket_path)]
                    else:
                        cmd = None

                if cmd is None:
                    raise RuntimeError('No lp/lpr command available')

                subprocess.check_call(cmd)
            except Exception as exc:
                self._log_error(f"No se pudo imprimir vía CUPS ({device}): {exc}")
                return False

            self.reset()
            return True

        # Fallback: try to open as a file/device on POSIX
        try:
            with open(device, "wb") as printer:
                printer.write(self.buffer)
                printer.flush()
        except Exception as exc:
            self._log_error(f"No se pudo imprimir en {device}: {exc}")
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