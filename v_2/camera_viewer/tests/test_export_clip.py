"""Exportar un clip: rangos, nombres, reempaquetado, verificación y ejecutor, con un DVR falso.
Correr desde v_2/: .venv/bin/python -m unittest camera_viewer.tests.test_export_clip -v"""
from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
import unittest.mock
from concurrent.futures import Future
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from camera_viewer import export_clip  # noqa: E402
from camera_viewer.download_manager import DownloadPriority  # noqa: E402
from camera_viewer.export_clip import ClipRange, ExportError, start_export  # noqa: E402

T0 = datetime(2026, 9, 19, 10, 5, 30)
FFMPEG = export_clip.find_ffmpeg()


def make_video(seconds: float, fps: int = 30) -> Path:
    folder = Path(tempfile.mkdtemp())
    path = folder / "fake.avi"  # OpenCV solo sabe escribir formatos conocidos: se renombra a .dav como lo entrega el DVR
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (64, 48))
    for i in range(int(seconds * fps)):
        writer.write(np.full((48, 64, 3), i % 200, dtype=np.uint8))
    writer.release()
    return path.rename(folder / f"ch_{time.monotonic_ns()}.dav")


class FakeDVR:
    """submit() falso: cada descarga produce un video sintético de la duración pedida."""

    def __init__(self, delay: float = 0.0, fail_first: int = 0, seconds_delta: float = 0.0) -> None:
        self.calls: list[tuple] = []
        self.delay, self.fail_first, self.seconds_delta = delay, fail_first, seconds_delta

    def __call__(self, host, user, password, channel, start, end, priority, stop) -> Future:
        self.calls.append((channel, start, end, priority))
        future: Future = Future()
        if self.fail_first > 0:
            self.fail_first -= 1
            future.set_result(None)
            return future

        def work() -> None:
            if self.delay:
                stop.wait(self.delay)
            if stop.is_set():
                future.set_result(None)
                return
            future.set_result(make_video((end - start).total_seconds() + self.seconds_delta))

        threading.Thread(target=work, daemon=True).start()
        return future


def collect(handle, timeout: float = 30.0) -> list[tuple]:
    events, deadline = [], time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            event = handle.events.get(timeout=0.2)
        except Exception:
            continue
        events.append(event)
        if event[0] == "finished":
            return events
    raise AssertionError(f"la exportación no terminó: {events}")


class HelpersTests(unittest.TestCase):
    def test_range_around_a_moment_is_clamped_to_what_is_recorded(self) -> None:
        r = ClipRange.around(T0, before=30, after=30)
        self.assertEqual((r.start, r.end, r.duration), (T0 - timedelta(seconds=30), T0 + timedelta(seconds=30), 60.0))
        clamped = ClipRange.around(T0, 30, 30, earliest=T0 - timedelta(seconds=10), latest=T0 + timedelta(seconds=12))
        self.assertEqual((clamped.start, clamped.end), (T0 - timedelta(seconds=10), T0 + timedelta(seconds=12)))

    def test_filenames_and_uniqueness(self) -> None:
        r = ClipRange(T0, T0 + timedelta(seconds=40))
        name = export_clip.clip_filename(2, r, ".mp4")
        self.assertEqual(name, "CAM2_2026-09-19_10-05-30_a_10-06-10.mp4")
        folder = Path(tempfile.mkdtemp())
        first = export_clip.unique_path(folder, name)
        first.write_bytes(b"x")
        self.assertEqual(export_clip.unique_path(folder, name).name, "CAM2_2026-09-19_10-05-30_a_10-06-10 (2).mp4")

    def test_size_estimate_and_format(self) -> None:
        r = ClipRange(T0, T0 + timedelta(seconds=60))
        self.assertAlmostEqual(export_clip.estimate_bytes(r, 4) / 1e6, 63.0, delta=1.0)  # 4 canales x 1 min ≈ 63 MB
        self.assertEqual(export_clip.format_size(2048), "2.0 KB")
        self.assertEqual(export_clip.format_size(5 * 1024 ** 3), "5.0 GB")

    def test_verify_detects_empty_unreadable_and_short_files(self) -> None:
        folder = Path(tempfile.mkdtemp())
        empty = folder / "e.dav"
        empty.write_bytes(b"")
        with self.assertRaises(ExportError):
            export_clip.verify_clip(empty, 10)
        garbage = folder / "g.dav"
        garbage.write_bytes(b"esto no es un video" * 100)
        with self.assertRaises(ExportError):
            export_clip.verify_clip(garbage, 10)
        good = make_video(10)
        self.assertIsNone(export_clip.verify_clip(good, 10))
        self.assertIn("dura 10 s de los 30 s pedidos", export_clip.verify_clip(good, 30))


class ExportRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp()) / "Cámaras"
        self.range = ClipRange(T0, T0 + timedelta(seconds=4))

    def run_export(self, dvr, channels=(1, 2), ffmpeg=None):
        handle = start_export("dvr", "u", "p", list(channels), self.range, self.folder, submit=dvr, ffmpeg=ffmpeg)
        return handle, collect(handle)

    def files(self) -> list[str]:
        return sorted(p.name for p in self.folder.iterdir()) if self.folder.exists() else []

    def test_exports_every_channel_as_dav_when_ffmpeg_is_not_available(self) -> None:
        dvr = FakeDVR()
        _, events = self.run_export(dvr, (1, 2), ffmpeg=None)
        done = [e for e in events if e[0] == "done"]
        self.assertEqual(sorted(e[1] for e in done), [1, 2])
        self.assertEqual(self.files(), ["CAM1_2026-09-19_10-05-30_a_10-05-34.dav", "CAM2_2026-09-19_10-05-30_a_10-05-34.dav"])
        self.assertTrue(all(e[3] is None for e in done))  # duración correcta: sin aviso
        self.assertEqual(events[-1][0], "finished")

    def test_the_exact_range_is_requested_from_the_dvr_with_export_priority(self) -> None:
        dvr = FakeDVR()
        self.run_export(dvr, (1, 3), ffmpeg=None)
        self.assertEqual(sorted(dvr.calls), [(1, T0, T0 + timedelta(seconds=4), DownloadPriority.EXPORT), (3, T0, T0 + timedelta(seconds=4), DownloadPriority.EXPORT)])

    @unittest.skipUnless(FFMPEG, "ffmpeg no está instalado")
    def test_remuxes_to_mp4_without_reencoding_and_the_result_opens(self) -> None:
        _, events = self.run_export(FakeDVR(), (1,), ffmpeg=FFMPEG)
        done = [e for e in events if e[0] == "done"]
        self.assertEqual(len(done), 1)
        path = Path(done[0][2])
        self.assertEqual(path.suffix, ".mp4")
        self.assertIsNone(export_clip.verify_clip(path, 4.0))
        self.assertEqual(self.files(), [path.name])  # sin .part ni temporales

    def test_a_shorter_clip_is_kept_with_a_warning(self) -> None:
        _, events = self.run_export(FakeDVR(seconds_delta=-2.5), (1,), ffmpeg=None)
        done = [e for e in events if e[0] == "done"][0]
        self.assertIn("pedidos", done[3])
        self.assertEqual(len(self.files()), 1)

    def test_a_failed_download_is_retried_once(self) -> None:
        dvr = FakeDVR(fail_first=1)
        with unittest.mock.patch.object(export_clip, "DOWNLOAD_RETRY_DELAY", 0.05):
            _, events = self.run_export(dvr, (1,), ffmpeg=None)
        self.assertEqual([e[0] for e in events if e[0] in ("done", "failed")], ["done"])
        self.assertEqual(len(dvr.calls), 2)
        self.assertIn(("state", 1, "Reintentando la descarga…"), events)

    def test_two_failures_report_the_channel_and_leave_nothing_behind(self) -> None:
        with unittest.mock.patch.object(export_clip, "DOWNLOAD_RETRY_DELAY", 0.05):
            _, events = self.run_export(FakeDVR(fail_first=99), (1, 2), ffmpeg=None)
        failed = [e for e in events if e[0] == "failed"]
        self.assertEqual(sorted(e[1] for e in failed), [1, 2])
        self.assertIn("No se pudo descargar", failed[0][2])
        self.assertEqual(self.files(), [])
        self.assertEqual(events[-1], ("finished", {1: None, 2: None}))

    def test_one_channel_failing_does_not_stop_the_others(self) -> None:
        class OneBad(FakeDVR):
            def __call__(self, host, user, password, channel, start, end, priority, stop):
                if channel == 2:
                    future: Future = Future()
                    future.set_result(None)
                    self.calls.append((channel,))
                    return future
                return super().__call__(host, user, password, channel, start, end, priority, stop)

        with unittest.mock.patch.object(export_clip, "DOWNLOAD_RETRY_DELAY", 0.05):
            _, events = self.run_export(OneBad(), (1, 2, 3), ffmpeg=None)
        self.assertEqual(sorted(e[1] for e in events if e[0] == "done"), [1, 3])
        self.assertEqual(sorted(e[1] for e in events if e[0] == "failed"), [2])

    def test_cancel_stops_pending_channels_and_cleans_up(self) -> None:
        handle = start_export("dvr", "u", "p", [1, 2], self.range, self.folder, submit=FakeDVR(delay=30.0), ffmpeg=None)
        time.sleep(0.5)
        handle.cancel()
        events = collect(handle, 10)
        self.assertEqual(sorted(e[1] for e in events if e[0] == "failed"), [1, 2])
        self.assertTrue(all(e[2] == "Cancelado" for e in events if e[0] == "failed"))
        self.assertEqual(self.files(), [])

    def test_an_existing_file_is_never_overwritten(self) -> None:
        self.run_export(FakeDVR(), (1,), ffmpeg=None)
        _, events = self.run_export(FakeDVR(), (1,), ffmpeg=None)
        self.assertEqual(len(self.files()), 2)
        self.assertTrue(any("(2)" in name for name in self.files()))

    def test_the_source_temp_file_is_always_removed(self) -> None:
        made: list[Path] = []

        class Recording(FakeDVR):
            def __call__(self, *args):
                future = super().__call__(*args)
                future.add_done_callback(lambda f: f.result() and made.append(f.result()))
                return future

        self.run_export(Recording(), (1, 2), ffmpeg=None)
        time.sleep(0.2)
        self.assertTrue(made)
        self.assertTrue(all(not path.exists() for path in made))


if __name__ == "__main__":
    unittest.main()
