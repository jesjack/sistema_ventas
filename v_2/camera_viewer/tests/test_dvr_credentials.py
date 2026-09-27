"""camera_viewer/dvr_credentials.py: de dónde salen host/usuario/contraseña del DVR ahora que ya
no están quemados en el código (por poco se suben a GitHub el 2026-09-26). Correr desde v_2/:
.venv/bin/python -m unittest camera_viewer.tests.test_dvr_credentials -v"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from camera_viewer import dvr_credentials as mod


class DvrCredentialsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.env_file = self.tmp / ".env"

    def test_reads_from_the_env_file_when_no_environment_variable_is_set(self) -> None:
        self.env_file.write_text("DVR_HOST=10.0.0.5\nDVR_USER=ana\nDVR_PASSWORD=clave123\n")
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(mod.dvr_credentials(self.env_file), ("10.0.0.5", "ana", "clave123"))

    def test_ignores_blank_lines_and_comments_and_strips_quotes(self) -> None:
        self.env_file.write_text('# comentario\n\nDVR_HOST="10.0.0.5"\nDVR_USER=\'ana\'\nDVR_PASSWORD=clave123\n')
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(mod.dvr_credentials(self.env_file), ("10.0.0.5", "ana", "clave123"))

    def test_an_environment_variable_overrides_the_env_file(self) -> None:
        self.env_file.write_text("DVR_HOST=10.0.0.5\nDVR_USER=ana\nDVR_PASSWORD=clave123\n")
        with mock.patch.dict("os.environ", {"DVR_HOST": "127.0.0.1"}, clear=True):
            host, _, _ = mod.dvr_credentials(self.env_file)
        self.assertEqual(host, "127.0.0.1")

    def test_missing_env_file_and_no_environment_variables_raises_a_clear_error(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                mod.dvr_credentials(self.tmp / "no_existe.env")
        self.assertIn("DVR_HOST", str(ctx.exception))
        self.assertIn("DVR_USER", str(ctx.exception))
        self.assertIn("DVR_PASSWORD", str(ctx.exception))

    def test_a_single_missing_value_is_named_specifically(self) -> None:
        self.env_file.write_text("DVR_HOST=10.0.0.5\nDVR_USER=ana\n")
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                mod.dvr_credentials(self.env_file)
        self.assertIn("DVR_PASSWORD", str(ctx.exception))
        self.assertNotIn("DVR_HOST,", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
