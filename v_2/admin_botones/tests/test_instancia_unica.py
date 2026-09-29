"""Instancia única de admin_botones vía socket Unix, sin Qt. Correr desde v_2/:
.venv/bin/python -m unittest admin_botones.tests.test_instancia_unica -v"""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from admin_botones.instancia_unica import _ruta_socket, escuchar, hay_instancia_activa


class InstanciaUnicaTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.base_dir = Path(self._dir.name)

    def test_sin_nadie_escuchando_no_hay_instancia_activa(self) -> None:
        self.assertFalse(hay_instancia_activa(self.base_dir))

    def test_con_alguien_escuchando_hay_instancia_activa_y_le_llega_el_ping(self) -> None:
        pings = []
        listo = threading.Event()

        def al_recibir_ping():
            pings.append(1)
            listo.set()

        hilo = threading.Thread(target=escuchar, args=(self.base_dir, al_recibir_ping), daemon=True)
        hilo.start()
        try:
            # escuchar() hace bind()/listen() antes del primer accept(), pero eso pasa en otro
            # hilo -- se espera a que el archivo de socket exista para no competir con esa carrera.
            ruta = _ruta_socket(self.base_dir)
            for _ in range(50):
                if ruta.exists():
                    break
                time.sleep(0.02)

            self.assertTrue(hay_instancia_activa(self.base_dir))
            self.assertTrue(listo.wait(timeout=1.0))
            self.assertEqual(pings, [1])
        finally:
            # El hilo de escuchar() queda bloqueado para siempre en accept(); no hay forma limpia
            # de pararlo desde afuera (es daemon, muere solo con el proceso de la prueba), así
            # que no se hace join().
            pass

    def test_un_socket_viejo_sin_nadie_detras_se_considera_libre_y_se_limpia(self) -> None:
        ruta = _ruta_socket(self.base_dir)
        ruta.write_text("basura de una corrida anterior que no cerró limpio")

        self.assertFalse(hay_instancia_activa(self.base_dir))
        self.assertFalse(ruta.exists())


if __name__ == "__main__":
    unittest.main()
