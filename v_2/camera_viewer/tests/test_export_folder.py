"""La carpeta de guardado debe ser la de vídeos del usuario REAL (no /root). Correr desde v_2/:
.venv/bin/python -m unittest camera_viewer.tests.test_export_folder -v"""
from __future__ import annotations

import os
import pwd
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from camera_viewer import export_clip, launcher, shared_paths


def write_dirs(home: Path, videos: str) -> None:
    (home / ".config").mkdir(parents=True, exist_ok=True)
    (home / ".config" / "user-dirs.dirs").write_text(f'XDG_DESKTOP_DIR="$HOME/Escritorio"\nXDG_VIDEOS_DIR="{videos}"\n', encoding="utf-8")


class VideosFolderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp())

    def test_uses_the_folder_declared_by_xdg_even_if_it_has_an_accent(self) -> None:
        write_dirs(self.home, "$HOME/Vídeos")
        self.assertEqual(export_clip.videos_folder(self.home), self.home / "Vídeos")

    def test_english_systems(self) -> None:
        write_dirs(self.home, "$HOME/Videos")
        self.assertEqual(export_clip.videos_folder(self.home), self.home / "Videos")

    def test_without_config_it_uses_whichever_folder_exists(self) -> None:
        (self.home / "Vídeos").mkdir()
        self.assertEqual(export_clip.videos_folder(self.home), self.home / "Vídeos")
        other = Path(tempfile.mkdtemp())
        (other / "Videos").mkdir()
        self.assertEqual(export_clip.videos_folder(other), other / "Videos")

    def test_with_nothing_at_all_it_falls_back_to_videos(self) -> None:
        self.assertEqual(export_clip.videos_folder(self.home), self.home / "Videos")

    def test_a_config_that_points_to_the_home_itself_is_ignored(self) -> None:
        write_dirs(self.home, "$HOME/")  # XDG lo usa cuando el usuario "desactiva" la carpeta
        self.assertEqual(export_clip.videos_folder(self.home), self.home / "Videos")


class UserHomeTests(unittest.TestCase):
    def test_it_ignores_a_wrong_HOME_like_the_one_inherited_from_root(self) -> None:
        with mock.patch.dict(os.environ, {"HOME": "/root"}):
            self.assertEqual(export_clip.user_home(), Path(pwd.getpwuid(os.geteuid()).pw_dir))
            self.assertNotEqual(export_clip.default_export_folder().parts[:2], ("/", "root"))

    def test_as_root_through_sudo_it_uses_the_invoking_users_home(self) -> None:
        fake = types.SimpleNamespace(pw_dir="/home/alguien")
        with mock.patch.object(os, "geteuid", return_value=0), mock.patch.dict(os.environ, {"SUDO_USER": "alguien"}), mock.patch.object(
            pwd, "getpwnam", return_value=fake
        ):
            self.assertEqual(export_clip.user_home(), Path("/home/alguien"))

    def test_an_unknown_user_falls_back_to_path_home(self) -> None:
        with mock.patch.object(os, "geteuid", return_value=0), mock.patch.dict(os.environ, {"SUDO_USER": "nadie"}), mock.patch.object(
            pwd, "getpwnam", side_effect=KeyError
        ):
            self.assertEqual(export_clip.user_home(), Path.home())


class OwnershipTests(unittest.TestCase):
    def test_new_folders_and_files_go_to_the_invoking_user_when_running_as_root(self) -> None:
        base = Path(tempfile.mkdtemp())
        target = base / "a" / "b"
        with mock.patch.object(os, "geteuid", return_value=0), mock.patch.dict(os.environ, {"SUDO_UID": "1000", "SUDO_GID": "1001"}), mock.patch.object(
            os, "chown"
        ) as chown:
            export_clip.make_folder(target)
            export_clip.own_as_user(target / "x.mp4")
        chowned = [call.args[0] for call in chown.call_args_list]
        self.assertEqual(chowned, [base / "a", base / "a" / "b", target / "x.mp4"])
        self.assertTrue(all(call.args[1:] == (1000, 1001) for call in chown.call_args_list))
        self.assertTrue(target.is_dir())

    def test_nothing_is_changed_when_not_root(self) -> None:
        base = Path(tempfile.mkdtemp())
        with mock.patch.object(os, "chown") as chown:
            export_clip.make_folder(base / "x")
            export_clip.own_as_user(base / "x")
        chown.assert_not_called()


class LauncherEnvTests(unittest.TestCase):
    def setUp(self) -> None:
        # launcher._prepare_log_file() ahora llama a ensure_shared_root() (2026-09-28), que
        # intenta "setfacl -b" vía subprocess -- estas pruebas ya mockean subprocess.Popen
        # globalmente para inspeccionar los kwargs del proceso REAL que se lanza, y ese mismo
        # mock rompe la llamada interna a setfacl (no se comporta como un Popen de verdad). No
        # hace falta setfacl para lo que prueba esta clase: se lo quita del camino.
        patch = mock.patch.object(shared_paths.shutil, "which", return_value=None)
        patch.start()
        self.addCleanup(patch.stop)

    def launch(self, environ: dict, euid: int, func=None) -> dict:
        base = Path(tempfile.mkdtemp())
        with mock.patch.dict(os.environ, environ, clear=False), mock.patch.object(os, "geteuid", return_value=euid), mock.patch.object(
            launcher, "find_python_executable", return_value=Path("/usr/bin/python3")
        ), mock.patch.object(subprocess, "Popen") as popen, mock.patch.object(
            pwd, "getpwnam", return_value=types.SimpleNamespace(pw_dir="/home/jesjack", pw_name="jesjack")
        ):
            (func or launcher.launch_detached)(base)
        return popen.call_args

    def test_the_child_gets_the_real_users_home_when_privileges_are_dropped(self) -> None:
        kwargs = self.launch({"SUDO_USER": "jesjack", "SUDO_GID": "1000", "HOME": "/root", "USER": "root", "XDG_CONFIG_HOME": "/root/.config"}, euid=0).kwargs
        self.assertEqual(kwargs["user"], "jesjack")
        env = kwargs["env"]
        self.assertEqual((env["HOME"], env["USER"], env["LOGNAME"]), ("/home/jesjack", "jesjack", "jesjack"))
        self.assertNotIn("XDG_CONFIG_HOME", env)

    def test_nothing_changes_when_not_running_as_root(self) -> None:
        kwargs = self.launch({"HOME": "/home/jesjack"}, euid=1000).kwargs
        self.assertNotIn("user", kwargs)
        self.assertEqual(kwargs["env"]["HOME"], "/home/jesjack")

    def test_the_child_gets_the_real_users_supplementary_groups(self) -> None:
        """2026-09-24: sin esto, subprocess.Popen nunca llama a setgroups() en el hijo (solo lo
        hace si se le pasa extra_groups) -- el proceso bajado se queda con los grupos de ROOT,
        no los del usuario real, y por eso otro usuario del grupo del negocio (p. ej. tpv_yaeli)
        no tenía ningún permiso sobre los archivos compartidos que otro ya había creado."""
        base = Path(tempfile.mkdtemp())
        with mock.patch.dict(os.environ, {"SUDO_USER": "nancy", "SUDO_GID": "1004"}, clear=False), mock.patch.object(
            os, "geteuid", return_value=0
        ), mock.patch.object(launcher, "find_python_executable", return_value=Path("/usr/bin/python3")), mock.patch.object(
            subprocess, "Popen"
        ) as popen, mock.patch.object(pwd, "getpwnam", return_value=types.SimpleNamespace(pw_dir="/home/nancy", pw_name="nancy")), mock.patch.object(
            os, "getgrouplist", return_value=[1004, 1003]
        ) as getgrouplist:
            launcher.launch_detached(base)
        getgrouplist.assert_called_once_with("nancy", 1004)
        self.assertEqual(popen.call_args.kwargs["extra_groups"], [1004, 1003])

    def test_an_unknown_user_still_drops_uid_gid_it_just_skips_extra_groups(self) -> None:
        base = Path(tempfile.mkdtemp())
        with mock.patch.dict(os.environ, {"SUDO_USER": "fantasma", "SUDO_GID": "9999"}, clear=False), mock.patch.object(
            os, "geteuid", return_value=0
        ), mock.patch.object(launcher, "find_python_executable", return_value=Path("/usr/bin/python3")), mock.patch.object(
            subprocess, "Popen"
        ) as popen, mock.patch.object(pwd, "getpwnam", side_effect=KeyError("fantasma")), mock.patch.object(
            os, "getgrouplist", side_effect=KeyError("fantasma")
        ):
            launcher.launch_detached(base)
        kwargs = popen.call_args.kwargs
        self.assertEqual(kwargs["user"], "fantasma")
        self.assertNotIn("extra_groups", kwargs)

    def test_launch_archiver_runs_the_archiver_module_dropped_to_the_real_user_too(self) -> None:
        call = self.launch({"SUDO_USER": "jesjack", "SUDO_GID": "1000", "HOME": "/root"}, euid=0, func=launcher.launch_archiver)
        self.assertEqual(call.args[0], ["/usr/bin/python3", "-m", "camera_viewer.archiver"])
        self.assertEqual(call.kwargs["user"], "jesjack")

    def test_launch_detached_and_launch_archiver_use_separate_log_files(self) -> None:
        base = Path(tempfile.mkdtemp())
        with mock.patch.object(launcher, "find_python_executable", return_value=Path("/usr/bin/python3")), mock.patch.object(
            subprocess, "Popen"
        ):
            launcher.launch_detached(base)
            launcher.launch_archiver(base)
        logs = base / "share" / "logs" / "camera_viewer"
        self.assertEqual(len(list(logs.glob("run_*.log"))), 1)
        self.assertEqual(len(list(logs.glob("archiver_run_*.log"))), 1)

    def test_launch_archiver_reports_a_missing_venv_the_same_way(self) -> None:
        base = Path(tempfile.mkdtemp())
        with mock.patch.object(launcher, "find_python_executable", return_value=None):
            with self.assertRaises(FileNotFoundError):
                launcher.launch_archiver(base)


class ParseFolderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(tempfile.mkdtemp())

    def test_an_existing_folder_and_one_that_can_still_be_created_are_valid(self) -> None:
        self.assertEqual(export_clip.parse_folder(str(self.base)), self.base)
        self.assertEqual(export_clip.parse_folder(f"  {self.base}/a/b  "), self.base / "a" / "b")

    def test_empty_relative_or_through_a_file_are_not(self) -> None:
        (self.base / "archivo").write_text("x")
        for text in ("", "   ", "relativa/carpeta", str(self.base / "archivo"), str(self.base / "archivo" / "sub")):
            self.assertIsNone(export_clip.parse_folder(text), text)

    def test_tilde_is_the_real_users_home_not_dollar_home(self) -> None:
        with mock.patch.object(export_clip, "user_home", return_value=self.base):
            self.assertEqual(export_clip.parse_folder("~/Vídeos"), self.base / "Vídeos")
            self.assertEqual(export_clip.parse_folder("~"), self.base)


if __name__ == "__main__":
    unittest.main()
