"""hardware.ticket_printer._escribir_con_limite_de_tiempo: una impresora atascada no debe colgar
para siempre a quien le pide imprimir. 2026-09-23: sin este límite, escribir a /dev/usb/lpN se
quedaba esperando indefinidamente y se llevaba con ella al único hilo que escucha los botones de
la hoja (ver services/button_bridge.py y nucleo/controlador_venta.py, mismo día)."""

import os
import tempfile
import threading
import time
import unittest

from hardware.ticket_printer import _escribir_con_limite_de_tiempo


class TestEscrituraConLimiteDeTiempo(unittest.TestCase):
    def test_un_dispositivo_que_nunca_responde_no_cuelga_para_siempre(self):
        with tempfile.TemporaryDirectory() as tmp:
            fifo = os.path.join(tmp, "impresora.fifo")
            os.mkfifo(fifo)  # nadie la lee -> escribir ahí bloquea de verdad, como el /dev/usb/lpN real

            inicio = time.monotonic()
            with self.assertRaises(TimeoutError):
                _escribir_con_limite_de_tiempo(fifo, b"hola", timeout=0.3)
            transcurrido = time.monotonic() - inicio

            self.assertLess(transcurrido, 1.0)  # se recuperó, no se quedó esperando

    def test_una_escritura_normal_llega_completa(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = os.path.join(tmp, "ticket.bin")
            ok = _escribir_con_limite_de_tiempo(ruta, b"contenido del ticket", timeout=2)
            self.assertTrue(ok)
            self.assertEqual(open(ruta, "rb").read(), b"contenido del ticket")

    def test_un_error_real_del_dispositivo_se_propaga(self):
        with self.assertRaises(OSError):
            _escribir_con_limite_de_tiempo("/ruta/que/no/existe/ticket.bin", b"x", timeout=2)

    def test_no_deja_hilos_bloqueando_el_cierre_del_proceso(self):
        with tempfile.TemporaryDirectory() as tmp:
            fifo = os.path.join(tmp, "impresora.fifo")
            os.mkfifo(fifo)

            antes = {t.name for t in threading.enumerate()}
            try:
                _escribir_con_limite_de_tiempo(fifo, b"hola", timeout=0.2)
            except TimeoutError:
                pass

            nuevos = [t for t in threading.enumerate() if t.name not in antes]
            self.assertTrue(all(t.daemon for t in nuevos))  # no impiden que el proceso termine


if __name__ == "__main__":
    unittest.main()
