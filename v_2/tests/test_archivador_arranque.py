"""El archivador pasivo de camera_viewer (ver camera_viewer/archiver.py) arranca junto con el
POS. Se prueba con dobles: nunca se lanza un subproceso real ni se toca camera_viewer/.

Correr desde v_2/ con el python del SISTEMA (el .venv no tiene `uno`):
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_archivador_arranque -v"""

import subprocess
import unittest
from unittest import mock

from nucleo import arranque


class IniciarArchivadorTests(unittest.TestCase):
    def test_launches_it_and_reports_the_pid(self) -> None:
        proceso_falso = mock.Mock(pid=4242)
        with mock.patch("camera_viewer.launcher.launch_archiver", return_value=proceso_falso) as launch:
            proceso = arranque._iniciar_archivador_de_camaras("/base")
        launch.assert_called_once_with("/base")
        self.assertIs(proceso, proceso_falso)

    def test_a_missing_camera_viewer_venv_is_reported_not_raised(self) -> None:
        with mock.patch("camera_viewer.launcher.launch_archiver", side_effect=FileNotFoundError("sin venv")):
            proceso = arranque._iniciar_archivador_de_camaras("/base")
        self.assertIsNone(proceso)

    def test_only_imports_camera_viewer_launcher_not_the_whole_package_eagerly(self) -> None:
        """camera_viewer importa OpenCV/PySide6 -- nucleo/arranque.py corre en el Python
        embebido de LibreOffice, que no los tiene. El import debe ser LOCAL a la función, no uno
        de los de arriba del archivo (los que sí corren con solo importar el módulo)."""
        import ast
        import inspect

        source = inspect.getsource(arranque)
        top_level_imports = [node for node in ast.parse(source).body if isinstance(node, (ast.Import, ast.ImportFrom))]
        modules = {getattr(node, "module", None) or node.names[0].name for node in top_level_imports}
        self.assertFalse(any(m and m.startswith("camera_viewer") for m in modules))


class DetenerArchivadorTests(unittest.TestCase):
    def test_terminates_and_waits(self) -> None:
        proceso = mock.Mock()
        arranque._detener_archivador_de_camaras(proceso)
        proceso.terminate.assert_called_once()
        proceso.wait.assert_called_once_with(timeout=5)
        proceso.kill.assert_not_called()

    def test_kills_it_if_it_does_not_stop_in_time(self) -> None:
        proceso = mock.Mock()
        proceso.wait.side_effect = subprocess.TimeoutExpired(cmd="archiver", timeout=5)
        arranque._detener_archivador_de_camaras(proceso)
        proceso.kill.assert_called_once()

    def test_a_kill_failure_never_propagates(self) -> None:
        proceso = mock.Mock()
        proceso.terminate.side_effect = RuntimeError("ya no existe")
        proceso.kill.side_effect = RuntimeError("tampoco")
        arranque._detener_archivador_de_camaras(proceso)  # no lanza


class EjecutarWiresItUpTests(unittest.TestCase):
    """`ejecutar()` arranca el archivador justo tras asegurar la instancia única, y solo
    registra el cierre ordenado si de verdad se lanzó algo -- sin llegar a conectar con
    LibreOffice de verdad (se corta ahí, con una excepción, para no necesitar un `uno` real)."""

    def test_registers_the_stop_hook_only_when_a_process_actually_started(self) -> None:
        proceso_falso = mock.Mock(pid=1)
        with mock.patch.object(arranque, "asegurar_instancia_unica", return_value=True), mock.patch.object(
            arranque, "_iniciar_archivador_de_camaras", return_value=proceso_falso
        ) as iniciar, mock.patch.object(arranque, "conectar_libreoffice", side_effect=RuntimeError("corte a propósito")), mock.patch(
            "atexit.register"
        ) as atexit_register:
            with self.assertRaises(RuntimeError):
                arranque.ejecutar("/base")
        iniciar.assert_called_once_with("/base")
        atexit_register.assert_any_call(arranque._detener_archivador_de_camaras, proceso_falso)

    def test_no_stop_hook_when_nothing_started(self) -> None:
        with mock.patch.object(arranque, "asegurar_instancia_unica", return_value=True), mock.patch.object(
            arranque, "_iniciar_archivador_de_camaras", return_value=None
        ), mock.patch.object(arranque, "conectar_libreoffice", side_effect=RuntimeError("corte a propósito")), mock.patch(
            "atexit.register"
        ) as atexit_register:
            with self.assertRaises(RuntimeError):
                arranque.ejecutar("/base")
        for call in atexit_register.call_args_list:
            self.assertNotEqual(call.args[:1], (arranque._detener_archivador_de_camaras,))


if __name__ == "__main__":
    unittest.main()
