"""SheetButtonBridge sin UNO real: el hilo que sondea share/logs/events/ no debe morir ante un
fallo inesperado (ver el mismo problema documentado en nucleo/controlador_venta.py)."""

import io
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

from services.button_bridge import SheetButtonBridge


class TestWatchEventsSobrevive(unittest.TestCase):
    def crear_bridge(self, base_dir):
        documento = SimpleNamespace(getScriptProvider=lambda: None)
        bridge = SheetButtonBridge(uno_context=None, document=documento, base_dir=base_dir, poll_interval=0.05)
        bridge.prepare(clear_events=True)
        return bridge

    def test_un_fallo_inesperado_al_drenar_no_mata_el_hilo(self):
        with tempfile.TemporaryDirectory() as base_dir:
            bridge = self.crear_bridge(Path(base_dir))
            llamadas = []
            original = bridge._drain_events

            def drenar_que_falla_una_vez():
                llamadas.append(1)
                if len(llamadas) == 1:
                    raise RuntimeError("fallo de una sola vez")
                original()

            bridge._drain_events = drenar_que_falla_una_vez

            salida = io.StringIO()
            with redirect_stdout(salida):
                bridge.start()
                time.sleep(0.3)  # deja pasar varios ciclos de sondeo
                bridge.close()

            self.assertGreater(len(llamadas), 1)  # el hilo siguió vivo después del fallo
            self.assertIn("[FALLO INESPERADO] SheetButtonBridge", salida.getvalue())

    def test_el_hilo_confirma_que_arrancó(self):
        with tempfile.TemporaryDirectory() as base_dir:
            bridge = self.crear_bridge(Path(base_dir))
            salida = io.StringIO()
            with redirect_stdout(salida):
                bridge.start()
                time.sleep(0.15)
                bridge.close()
            self.assertIn("[button_bridge] Escuchando clics en", salida.getvalue())

    def test_un_clic_sin_handler_no_rompe_nada(self):
        with tempfile.TemporaryDirectory() as base_dir:
            bridge = self.crear_bridge(Path(base_dir))
            (bridge.events_dir / "1.evt").write_text("CLICK|nada", encoding="utf-8")

            salida = io.StringIO()
            with redirect_stdout(salida):
                bridge._drain_events()

            self.assertIn("Click sin handler: nada", salida.getvalue())
            self.assertEqual(list(bridge.events_dir.glob("*.evt")), [])

    def test_on_tick_se_llama_en_cada_ciclo_de_sondeo(self):
        with tempfile.TemporaryDirectory() as base_dir:
            documento = SimpleNamespace(getScriptProvider=lambda: None)
            llamadas = []
            bridge = SheetButtonBridge(
                uno_context=None, document=documento, base_dir=Path(base_dir),
                poll_interval=0.05, on_tick=lambda: llamadas.append(1),
            )
            bridge.prepare(clear_events=True)
            bridge.start()
            time.sleep(0.3)
            bridge.close()
            self.assertGreater(len(llamadas), 1)

    def test_un_on_tick_que_falla_no_mata_el_hilo(self):
        with tempfile.TemporaryDirectory() as base_dir:
            documento = SimpleNamespace(getScriptProvider=lambda: None)

            def on_tick_que_falla():
                raise RuntimeError("fallo en revisar_cambios")

            bridge = SheetButtonBridge(
                uno_context=None, document=documento, base_dir=Path(base_dir),
                poll_interval=0.05, on_tick=on_tick_que_falla,
            )
            bridge.prepare(clear_events=True)

            salida = io.StringIO()
            with redirect_stdout(salida):
                bridge.start()
                time.sleep(0.2)
                bridge.close()

            self.assertIn("[FALLO INESPERADO] SheetButtonBridge.on_tick", salida.getvalue())


if __name__ == "__main__":
    unittest.main()
