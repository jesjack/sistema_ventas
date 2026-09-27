"""Carpetas compartidas entre usuarios del sistema (share/runtime, y mas adelante el archivo de
grabaciones): permisos de grupo, no rutas reales del disco. Correr desde v_2/:
.venv/bin/python -m unittest camera_viewer.tests.test_shared_paths -v"""
from __future__ import annotations

import grp
import os
import shutil
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from camera_viewer import shared_paths

HAS_SETFACL = shutil.which("setfacl") and shutil.which("getfacl")


@unittest.skipUnless(os.name == "posix", "permisos estilo POSIX")
class ApplyUmaskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_umask = os.umask(0o022)  # se restaura abajo (os.umask no tiene "leer sin cambiar")
        self.addCleanup(os.umask, self.old_umask)

    def test_new_files_become_group_writable(self) -> None:
        shared_paths.apply_shared_umask()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "archivo"
            path.touch()
            mode = stat.S_IMODE(path.stat().st_mode)
        self.assertTrue(mode & stat.S_IWGRP, f"el grupo no puede escribir: {oct(mode)}")


@unittest.skipUnless(os.name == "posix", "permisos estilo POSIX")
class EnsureSharedRootTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))

    def test_creates_missing_parents(self) -> None:
        target = self.tmp / "a" / "b" / "c"
        shared_paths.ensure_shared_root(target)
        self.assertTrue(target.is_dir())

    def test_existing_folder_is_left_usable_not_an_error(self) -> None:
        target = self.tmp / "ya_existe"
        target.mkdir()
        shared_paths.ensure_shared_root(target)  # no lanza
        self.assertTrue(target.is_dir())

    def test_sets_the_setgid_bit_and_group_rwx(self) -> None:
        target = self.tmp / "compartida"
        shared_paths.ensure_shared_root(target)
        mode = stat.S_IMODE(target.stat().st_mode)
        self.assertTrue(mode & stat.S_ISGID, "falta el bit setgid: lo creado adentro no heredaría el grupo")
        self.assertEqual(mode & 0o770, 0o770)  # rwx para dueño y grupo
        self.assertEqual(mode & 0o007, 0)  # nada para el resto: son grabaciones/secretos del negocio

    def test_uses_the_named_group_when_the_process_belongs_to_it(self) -> None:
        own_groups = {g.gr_name for g in grp.getgrall() if os.getlogin() in g.gr_mem} | {grp.getgrgid(os.getgid()).gr_name}
        group = next(iter(own_groups), None)
        if group is None:
            self.skipTest("el usuario de la prueba no pertenece a ningún grupo con nombre")
        target = self.tmp / "con_grupo"
        shared_paths.ensure_shared_root(target, group=group)
        self.assertEqual(target.stat().st_gid, grp.getgrnam(group).gr_gid)

    def test_an_unknown_group_or_a_permission_error_is_never_fatal(self) -> None:
        target = self.tmp / "grupo_inexistente"
        shared_paths.ensure_shared_root(target, group="este-grupo-no-existe-de-verdad")  # no lanza
        self.assertTrue(target.is_dir())

        target2 = self.tmp / "sin_permiso"
        with mock.patch.object(shared_paths.os, "chown", side_effect=PermissionError):
            shared_paths.ensure_shared_root(target2)  # tampoco lanza
        self.assertTrue(target2.is_dir())

    def test_is_idempotent(self) -> None:
        target = self.tmp / "otra_vez"
        shared_paths.ensure_shared_root(target)
        shared_paths.ensure_shared_root(target)
        self.assertTrue(target.is_dir())

    def test_setfacl_missing_is_never_fatal(self) -> None:
        target = self.tmp / "sin_setfacl"
        with mock.patch.object(shared_paths.shutil, "which", return_value=None):
            shared_paths.ensure_shared_root(target)  # no lanza
        self.assertTrue(target.is_dir())


@unittest.skipUnless(HAS_SETFACL, "hace falta setfacl/getfacl")
class InheritedAclTests(unittest.TestCase):
    """El bug real de 2026-09-23: share/ (el POS) trae una ACL por defecto de "rwx para
    cualquiera" (para compartirlo por Samba), que TODO lo creado adentro hereda sin importar el
    chmod ni el umask -- una grabación guardada ahí habría quedado legible/escribible por
    cualquier usuario del sistema, no solo por el grupo del negocio."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        # Simula el share/ real: una carpeta con una ACL por defecto heredable de "todos pueden todo".
        subprocess.run(["setfacl", "-d", "-m", "other::rwx", str(self.tmp)], check=True)

    def facl(self, path: Path) -> str:
        return subprocess.run(["getfacl", "-p", str(path)], capture_output=True, text=True, check=True).stdout

    def test_without_the_fix_the_leak_is_real(self) -> None:
        """Prueba de control: sin pasar por ensure_shared_root, un mkdir normal SÍ hereda la ACL."""
        leaky = self.tmp / "sin_arreglo"
        leaky.mkdir()
        self.assertIn("other::rwx", self.facl(leaky))

    def test_ensure_shared_root_strips_the_inherited_default_acl(self) -> None:
        target = self.tmp / "carpeta_compartida"
        shared_paths.ensure_shared_root(target)
        self.assertNotIn("other::rwx", self.facl(target))

    def test_children_created_afterwards_no_longer_leak_to_other(self) -> None:
        # Las dos piezas juntas, como en un punto de entrada real (ver __main__.py/archiver.py):
        # ensure_shared_root() quita la ACL heredable, apply_shared_umask() cuida el resto.
        old_umask = os.umask(0o022)
        self.addCleanup(os.umask, old_umask)  # el umask es del PROCESO: no debe filtrarse a otras pruebas
        shared_paths.apply_shared_umask()
        target = self.tmp / "carpeta_compartida"
        shared_paths.ensure_shared_root(target)
        child = target / "ch1"
        child.mkdir()
        self.assertNotIn("other::rwx", self.facl(child))
        mode = stat.S_IMODE(child.stat().st_mode)
        self.assertEqual(mode & (stat.S_IROTH | stat.S_IWOTH | stat.S_IXOTH), 0)

    def test_a_setfacl_failure_is_never_fatal(self) -> None:
        target = self.tmp / "otra"
        with mock.patch.object(shared_paths.subprocess, "run", side_effect=OSError("no se pudo")):
            shared_paths.ensure_shared_root(target)  # no lanza
        self.assertTrue(target.is_dir())


class ReadyMarkerTests(unittest.TestCase):
    """El aviso "la ventana ya se mostró" que espera acciones/ver_camaras.py (ver
    dialogs/aviso_cargando.py) en vez de un tiempo fijo."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        patcher = mock.patch.object(shared_paths, "SHARE_RUNTIME_DIR", self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_path_is_named_after_the_pid(self) -> None:
        self.assertEqual(shared_paths.ready_marker_path(4242), self.tmp / "listo_4242.marker")
        self.assertNotEqual(shared_paths.ready_marker_path(1), shared_paths.ready_marker_path(2))

    def test_purge_removes_only_markers_older_than_max_age(self) -> None:
        old = shared_paths.ready_marker_path(1)
        new = shared_paths.ready_marker_path(2)
        old.touch()
        new.touch()
        old_time = time.time() - 1000
        os.utime(old, (old_time, old_time))
        shared_paths.purge_old_ready_markers(max_age=300.0)
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())

    def test_purge_with_no_runtime_dir_yet_does_not_fail(self) -> None:
        shutil.rmtree(self.tmp)
        shared_paths.purge_old_ready_markers()  # no lanza

    def test_purge_ignores_files_that_do_not_match_the_marker_pattern(self) -> None:
        (self.tmp / "otro_archivo.txt").write_text("x")
        shared_paths.purge_old_ready_markers(max_age=0.0)
        self.assertTrue((self.tmp / "otro_archivo.txt").exists())


if __name__ == "__main__":
    unittest.main()
