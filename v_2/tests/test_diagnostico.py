"""nucleo.diagnostico: el volcado de hilos bajo SIGUSR1 sirve para un hilo que se queda callado
sin morir (ver services/button_bridge.py, 2026-09-23). Se escribe en el archivo que se le pasa,
no en sys.stderr -- ver el comentario en activar_volcado_de_hilos sobre por qué."""

import os
import signal
import tempfile
import threading
import time
import unittest

from nucleo.diagnostico import activar_volcado_de_hilos


class TestVolcadoDeHilos(unittest.TestCase):
    def test_sigusr1_muestra_la_linea_donde_está_atascado_un_hilo(self):
        # faulthandler identifica cada hilo por su id de sistema, no por threading.Thread.name --
        # lo que sí muestra, y lo que sirve para reconocer cuál es, es el archivo/función/línea
        # donde quedó parado (aquí, la función "atascado" mientras dormía).
        with tempfile.TemporaryDirectory() as tmp:
            ruta = os.path.join(tmp, "volcado.log")
            with open(ruta, "w", encoding="utf-8") as archivo:
                activar_volcado_de_hilos(os.getpid(), archivo)

                listo = threading.Event()

                def atascado():
                    listo.set()
                    time.sleep(2)

                hilo = threading.Thread(target=atascado, name="HiloDePrueba", daemon=True)
                hilo.start()
                listo.wait(timeout=1)
                time.sleep(0.05)  # que el hilo ya esté dentro de time.sleep(2) al llegar la señal

                os.kill(os.getpid(), signal.SIGUSR1)
                time.sleep(0.2)

            texto = open(ruta, encoding="utf-8").read()
            self.assertIn("in atascado", texto)
            self.assertIn("test_diagnostico.py", texto)


if __name__ == "__main__":
    unittest.main()
