"""El botón "VER CÁMARAS" (acciones/ver_camaras.py): espera a que la ventana de camera_viewer
avise que ya se mostró (en vez de un tiempo fijo) antes de cerrar el aviso de carga. Con dobles:
nunca lanza un subproceso real ni toca camera_viewer/.

Correr desde v_2/ con el python del SISTEMA (el .venv no tiene `uno`):
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_ver_camaras -v"""

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from acciones import ver_camaras


class FakeAviso:
    def __init__(self) -> None:
        self._cerrado = False

    def cerrar(self) -> None:
        self._cerrado = True

    @property
    def cerrado(self) -> bool:
        return self._cerrado


class EsperarVentanaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def marcador(self, pid: int = 1) -> Path:
        return self.tmp / f"listo_{pid}.marker"

    def test_closes_as_soon_as_the_marker_appears(self) -> None:
        aviso = FakeAviso()
        proceso = mock.Mock()
        proceso.poll.return_value = None
        marcador = self.marcador()
        ver_camaras._esperar_ventana(proceso, marcador, aviso)
        self.assertFalse(aviso.cerrado)
        marcador.touch()
        for _ in range(50):
            if aviso.cerrado:
                break
            time.sleep(0.05)
        self.assertTrue(aviso.cerrado)

    def test_closes_if_the_process_exits_on_its_own_first(self) -> None:
        aviso = FakeAviso()
        proceso = mock.Mock()
        proceso.poll.side_effect = [None, None, 1]  # a la tercera consulta, ya terminó
        ver_camaras._esperar_ventana(proceso, self.marcador(), aviso)
        for _ in range(50):
            if aviso.cerrado:
                break
            time.sleep(0.05)
        self.assertTrue(aviso.cerrado)

    def test_does_nothing_if_the_notice_is_already_closed(self) -> None:
        aviso = FakeAviso()
        aviso.cerrar()  # p. ej. ya se agotó su propio tope de tiempo
        proceso = mock.Mock()
        proceso.poll.return_value = None
        ver_camaras._esperar_ventana(proceso, self.marcador(), aviso)
        time.sleep(0.3)
        proceso.poll.assert_not_called()  # el hilo vio "ya cerrado" y ni miró


class EjecutarTests(unittest.TestCase):
    """`ejecutar()` en sí, con camera_viewer.launcher/dialogs simulados -- sin abrir nada real."""

    def run_ejecutar(self, launch_detached, mostrar_aviso_temporal=None, mostrar_aviso_error=None, esperar=None):
        aviso = mostrar_aviso_temporal() if mostrar_aviso_temporal else FakeAviso()
        modulos = {
            "camera_viewer.launcher": mock.Mock(launch_detached=launch_detached),
            "camera_viewer.shared_paths": mock.Mock(ready_marker_path=lambda pid: Path(f"/tmp/listo_{pid}.marker")),
            "dialogs.aviso_cargando": mock.Mock(mostrar_aviso_temporal=mock.Mock(return_value=aviso)),
            "dialogs.aviso_error": mock.Mock(mostrar_aviso_error=mock.Mock()),
        }
        with mock.patch.dict("sys.modules", modulos), mock.patch.object(ver_camaras, "_esperar_ventana", esperar or mock.Mock()):
            ctx = {"context": "ctx-uno-falso", "BASE_DIR": Path("/base")}
            ver_camaras.ejecutar(ctx)  # decorado con @usar_contexto: así sí inyecta "context"/"BASE_DIR"
        return aviso, modulos

    def test_a_successful_launch_waits_for_the_window_instead_of_closing_right_away(self) -> None:
        proceso = mock.Mock(pid=4242)
        vigilar = mock.Mock()
        aviso, modulos = self.run_ejecutar(mock.Mock(return_value=proceso), esperar=vigilar)
        vigilar.assert_called_once()
        args = vigilar.call_args[0]
        self.assertIs(args[0], proceso)
        modulos["dialogs.aviso_error"].mostrar_aviso_error.assert_not_called()

    def test_a_missing_venv_closes_the_notice_right_away_and_shows_the_real_error(self) -> None:
        vigilar = mock.Mock()
        aviso, modulos = self.run_ejecutar(mock.Mock(side_effect=FileNotFoundError("sin venv")), esperar=vigilar)
        self.assertTrue(aviso.cerrado)
        vigilar.assert_not_called()
        modulos["dialogs.aviso_error"].mostrar_aviso_error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
