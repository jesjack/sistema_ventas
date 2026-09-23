"""Recompresión de un segmento aterrizado (GPU con reserva a CPU). Necesita ffmpeg real (no hay
DVR de por medio: trabaja sobre un video sintético). Correr desde v_2/:
.venv/bin/python -m unittest camera_viewer.tests.test_archive_compactor -v"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from camera_viewer import archive_compactor as comp
from camera_viewer.export_clip import ExportError

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def make_source(path: Path, seconds: float = 3.0, size: str = "96x64") -> Path:
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=10:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-f", "mpegts", str(path)],
        check=True,
    )
    return path


class FindVaapiDeviceTests(unittest.TestCase):
    def test_returns_the_first_candidate_that_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing"
            present = Path(tmp) / "present"
            present.touch()
            self.assertEqual(comp.find_vaapi_device((str(missing), str(present))), str(present))

    def test_none_when_nothing_exists(self) -> None:
        self.assertIsNone(comp.find_vaapi_device(("/no/existe/1", "/no/existe/2")))


class CommandTests(unittest.TestCase):
    def test_gpu_command_uses_vaapi_and_a_time_based_keyframe_interval(self) -> None:
        command = comp.gpu_command("ffmpeg", "/dev/dri/renderD128", Path("in.dav"), Path("out.mp4"), 30)
        joined = " ".join(command)
        self.assertIn("h264_vaapi", joined)
        self.assertIn("/dev/dri/renderD128", joined)
        self.assertIn("-qp 30", joined)
        self.assertIn("n_forced*4", joined)

    def test_cpu_command_uses_libx264_and_the_same_keyframe_interval(self) -> None:
        command = comp.cpu_command("ffmpeg", Path("in.dav"), Path("out.mp4"), 30)
        joined = " ".join(command)
        self.assertIn("libx264", joined)
        self.assertIn("-crf 30", joined)
        self.assertIn("n_forced*4", joined)


@unittest.skipUnless(FFMPEG and FFPROBE, "hace falta ffmpeg/ffprobe")
class CompactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.source = make_source(self.tmp / "raw.dav")
        self.dest = self.tmp / "out.mp4"

    def test_compacting_shrinks_the_file_and_keeps_it_playable(self) -> None:
        result = comp.compact(self.source, self.dest, duration_seconds=3.0, ffmpeg=FFMPEG)
        self.assertTrue(self.dest.exists())
        self.assertEqual(result.path, self.dest)
        self.assertEqual(result.bytes, self.dest.stat().st_size)
        self.assertLess(result.bytes, self.source.stat().st_size)
        self.assertIsNone(comp.verify_output(self.dest, 3.0))  # abre bien y dura lo esperado
        self.assertEqual(list(self.tmp.glob(".*")), [])  # nada temporal quedó atrás

    def test_forcing_no_gpu_device_still_produces_a_valid_file_via_cpu(self) -> None:
        result = comp.compact(self.source, self.dest, duration_seconds=3.0, ffmpeg=FFMPEG, vaapi_device=None)
        self.assertFalse(result.used_gpu)
        self.assertTrue(self.dest.exists())

    def test_a_gpu_failure_falls_back_to_cpu_instead_of_giving_up(self) -> None:
        with mock.patch.object(comp, "gpu_command", side_effect=lambda *a: comp.cpu_command("false", *a[2:])):
            # "false" siempre falla: simula una GPU que arranca pero no puede -- debe caer a CPU real.
            result = comp.compact(self.source, self.dest, duration_seconds=3.0, ffmpeg=FFMPEG, vaapi_device="/dev/null")
        self.assertFalse(result.used_gpu)
        self.assertTrue(self.dest.exists())

    def test_without_ffmpeg_it_fails_clearly_and_touches_nothing(self) -> None:
        with self.assertRaises(comp.CompactionError):
            comp.compact(self.source, self.dest, duration_seconds=3.0, ffmpeg=None if not FFMPEG else "/no/existe/ffmpeg")
        self.assertFalse(self.dest.exists())

    def test_a_bad_source_never_leaves_a_partial_or_final_file(self) -> None:
        bad = self.tmp / "vacio.dav"
        bad.write_bytes(b"")
        with self.assertRaises(ExportError):
            comp.compact(bad, self.dest, duration_seconds=3.0, ffmpeg=FFMPEG)
        self.assertFalse(self.dest.exists())
        self.assertEqual(list(self.tmp.glob(".*")), [])

    def test_cancelling_stops_ffmpeg_and_leaves_nothing_behind(self) -> None:
        stop = threading.Event()
        # Grande y de varios segundos a propósito: que recomprimirlo por CPU tarde lo bastante
        # para que la cancelación de verdad lo interrumpa a medio camino (medido: a este tamaño,
        # una compresión completa de 8 s tarda más de 1 s, muy por encima de la espera de abajo).
        long_source = make_source(self.tmp / "largo.dav", seconds=8.0, size="960x540")

        def cancel_soon() -> None:
            time.sleep(0.3)
            stop.set()

        threading.Thread(target=cancel_soon, daemon=True).start()
        with mock.patch.object(comp, "FFMPEG_TIMEOUT", 30.0):
            with self.assertRaises(comp.CompactionError):
                comp.compact(long_source, self.dest, duration_seconds=8.0, ffmpeg=FFMPEG, vaapi_device=None, stop=stop)
        self.assertFalse(self.dest.exists())
        self.assertEqual([p for p in self.tmp.glob(".*") if p != long_source], [])

    def test_low_and_high_quality_constants_move_size_in_the_expected_direction(self) -> None:
        low_dest, high_dest = self.tmp / "low.mp4", self.tmp / "high.mp4"
        comp.compact(self.source, low_dest, duration_seconds=3.0, quality=comp.QUALITY_LOW, ffmpeg=FFMPEG, vaapi_device=None)
        comp.compact(self.source, high_dest, duration_seconds=3.0, quality=comp.QUALITY_HIGH, ffmpeg=FFMPEG, vaapi_device=None)
        self.assertLessEqual(low_dest.stat().st_size, high_dest.stat().st_size)


if __name__ == "__main__":
    unittest.main()
