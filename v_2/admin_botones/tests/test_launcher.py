"""launch_detached: no debe lanzar un segundo proceso si ya hay una ventana escuchando. Correr
desde v_2/: .venv/bin/python -m unittest admin_botones.tests.test_launcher -v"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from admin_botones import launcher


class LaunchDetachedTests(unittest.TestCase):
    def test_no_lanza_nada_si_ya_hay_una_instancia_activa(self) -> None:
        with mock.patch.object(launcher, "hay_instancia_activa", return_value=True), \
             mock.patch.object(launcher, "find_python_executable") as buscar_python, \
             mock.patch("subprocess.Popen") as popen:
            resultado = launcher.launch_detached(Path("/base"))

        self.assertIsNone(resultado)
        buscar_python.assert_not_called()
        popen.assert_not_called()

    def test_lanza_el_proceso_si_no_hay_instancia_activa(self) -> None:
        with mock.patch.object(launcher, "hay_instancia_activa", return_value=False), \
             mock.patch.object(launcher, "find_python_executable", return_value=Path("/base/.venv/bin/python3")), \
             mock.patch.object(launcher, "_prepare_log_file", return_value=Path("/tmp/no_deberia_escribirse.log")), \
             mock.patch("builtins.open", mock.mock_open()), \
             mock.patch("subprocess.Popen") as popen:
            launcher.launch_detached(Path("/base"))

        popen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
