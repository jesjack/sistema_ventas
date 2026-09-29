"""camera_viewer/launcher.py: el entorno que reciben los procesos hijos (la ventana, el
archivador). Correr desde v_2/: .venv/bin/python -m unittest camera_viewer.tests.test_launcher -v"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from camera_viewer import launcher


class CleanChildEnvTests(unittest.TestCase):
    def test_strips_python_path_variables_that_could_point_at_a_different_interpreter(self) -> None:
        fake_environ = {"PYTHONHOME": "/otro", "PYTHONPATH": "/otro/lib", "PATH": "/usr/bin"}
        with mock.patch.object(launcher.os, "environ", fake_environ):
            env = launcher._clean_child_env()
        self.assertNotIn("PYTHONHOME", env)
        self.assertNotIn("PYTHONPATH", env)
        self.assertEqual(env["PATH"], "/usr/bin")

    def test_forces_unbuffered_stdout_so_a_crash_does_not_lose_the_log(self) -> None:
        """2026-09-26: una ventana que sí cargó y funcionó tenía su log vacío -- stdout
        redirigido a un archivo queda con buffer de bloque completo por Python, y lo no
        volcado se pierde si el proceso muere de golpe en vez de cerrar limpio."""
        with mock.patch.object(launcher.os, "environ", {}):
            env = launcher._clean_child_env()
        self.assertEqual(env["PYTHONUNBUFFERED"], "1")


class PrepareLogFileTests(unittest.TestCase):
    """2026-09-28: logs/camera_viewer/ quedó a nombre de root en producción (el primer
    lanzamiento que la creó corrió con privilegios distintos) y ni el dueño real de la PC podía
    ya escribir ahí -- mismo tipo de bug que "VER CAMARAS no funciona para otros usuarios", solo
    que en esta carpeta faltaba el mismo arreglo."""

    def test_the_logs_folder_gets_the_same_shared_setup_as_share(self) -> None:
        base = Path(tempfile.mkdtemp())
        with mock.patch.object(launcher, "ensure_shared_root") as ensure_shared_root:
            launcher._prepare_log_file(base, prefix="run")
        ensure_shared_root.assert_called_once_with(base / "share" / "logs" / "camera_viewer")


if __name__ == "__main__":
    unittest.main()
