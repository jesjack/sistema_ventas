"""camera_viewer/launcher.py: el entorno que reciben los procesos hijos (la ventana, el
archivador). Correr desde v_2/: .venv/bin/python -m unittest camera_viewer.tests.test_launcher -v"""
from __future__ import annotations

import unittest
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


if __name__ == "__main__":
    unittest.main()
