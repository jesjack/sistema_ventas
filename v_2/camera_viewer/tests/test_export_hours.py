"""Exportar horas: el plan de trozos y tramos negros, y el motor con un DVR falso que genera video H.264
real (necesita ffmpeg). Correr desde v_2/: .venv/bin/python -m unittest camera_viewer.tests.test_export_hours -v"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from concurrent.futures import Future
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

import cv2

from camera_viewer import export_hours
from camera_viewer.clip import Clip
from camera_viewer.download_manager import DownloadPriority
from camera_viewer.export_hours import (
    HoursSpec,
    build_pieces,
    channel_pieces,
    gap_command,
    hour_blocks,
    hour_has_recording,
    merge_intervals,
    output_name,
    plan,
    start_hours_export,
)

DAY = date(2026, 9, 21)
FFMPEG = shutil.which("ffmpeg")


def at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 9, 21, hour, minute, second)


def clip(start: datetime, end: datetime, channel: int = 1) -> Clip:
    return Clip(channel, start, end)


class PlanTests(unittest.TestCase):
    def test_merge_intervals_joins_neighbours_and_ignores_tiny_holes(self) -> None:
        merged = merge_intervals([clip(at(9, 0), at(9, 10)), clip(at(9, 10, 1), at(9, 20)), clip(at(9, 30), at(9, 40))])
        self.assertEqual(merged, [(at(9, 0), at(9, 20)), (at(9, 30), at(9, 40))])  # 1 s de hueco: nada; 10 min: sí

    def test_hours_become_continuous_blocks(self) -> None:
        self.assertEqual(hour_blocks(DAY, [8, 9, 10, 14]), [(at(8), at(11)), (at(14), at(15))])
        self.assertEqual(hour_blocks(DAY, [10, 8, 9, 9]), [(at(8), at(11))])

    def test_the_limit_cuts_the_end_and_drops_what_starts_after_it(self) -> None:
        self.assertEqual(hour_blocks(DAY, [8, 9, 10], limit=at(9, 30)), [(at(8), at(9, 30))])
        self.assertEqual(hour_blocks(DAY, [8, 14], limit=at(9, 30)), [(at(8), at(9))])  # la de las 14 empieza después del límite

    def test_full_recording_is_cut_in_chunks_with_a_tiny_remainder_absorbed(self) -> None:
        pieces = build_pieces([(at(9), at(9, 5, 1))], [(at(8), at(10))], 120)
        self.assertEqual([(p.kind, p.seconds) for p in pieces], [("video", 120), ("video", 120), ("video", 61)])
        pieces = build_pieces([(at(9), at(9, 4, 30))], [(at(8), at(10))], 120)
        self.assertEqual([p.seconds for p in pieces], [120, 120, 30])

    def test_pieces_cover_the_block_without_holes_or_overlaps(self) -> None:
        recorded = [(at(9, 0), at(9, 20)), (at(9, 35), at(9, 50))]
        pieces = build_pieces([(at(9), at(10))], recorded, 120)
        self.assertEqual(pieces[0].start, at(9))
        self.assertEqual(pieces[-1].end, at(10))
        for before, after in zip(pieces, pieces[1:]):
            self.assertEqual(before.end, after.start)
        self.assertEqual([p.kind for p in pieces if p.kind == "gap"], ["gap", "gap"])
        self.assertEqual([(p.start, p.end) for p in pieces if p.kind == "gap"], [(at(9, 20), at(9, 35)), (at(9, 50), at(10))])

    def test_a_block_that_starts_before_the_first_recording_begins_with_black(self) -> None:
        pieces = build_pieces([(at(8), at(9))], [(at(8, 20), at(9, 30))], 600)
        self.assertEqual((pieces[0].kind, pieces[0].start, pieces[0].end), ("gap", at(8), at(8, 20)))
        self.assertEqual(pieces[1].kind, "video")

    def test_a_long_gap_is_split_into_several_black_pieces(self) -> None:
        pieces = build_pieces([(at(9), at(12))], [(at(9), at(9, 1)), (at(11, 59), at(12))], 120)
        gaps = [p for p in pieces if p.kind == "gap"]
        self.assertEqual(len(gaps), 6)  # casi 3 h a tramos de 30 min
        self.assertTrue(all(p.seconds <= export_hours.MAX_GAP_PIECE for p in gaps))

    def test_recordings_outside_the_block_are_ignored(self) -> None:
        pieces = build_pieces([(at(9), at(10))], [(at(7), at(8)), (at(11), at(12))], 120)
        self.assertEqual([(p.kind, p.seconds) for p in pieces], [("gap", 1800), ("gap", 1800)])

    def test_channel_pieces_stop_at_the_last_known_recording_no_trailing_black(self) -> None:
        spec = HoursSpec(DAY, {1: [9, 10]}, Path("/tmp/x"), {1: [clip(at(9), at(10, 20))]}, at(10, 50))
        pieces = channel_pieces(spec, 1, 600)
        self.assertEqual(pieces[-1].end, at(10, 20))
        self.assertEqual(pieces[-1].kind, "video")

    def test_the_current_hour_is_cut_at_now(self) -> None:
        spec = HoursSpec(DAY, {1: [10]}, Path("/tmp/x"), {1: [clip(at(9), at(11))]}, at(10, 15))
        self.assertEqual(channel_pieces(spec, 1, 600)[-1].end, at(10, 15))

    def test_a_channel_without_recordings_has_no_pieces(self) -> None:
        spec = HoursSpec(DAY, {1: [9], 2: [9]}, Path("/tmp/x"), {1: [clip(at(9), at(10))]}, at(12))
        self.assertEqual(channel_pieces(spec, 2), [])

    def test_hour_has_recording(self) -> None:
        clips = [clip(at(9, 30), at(10, 0, 0)), clip(at(11, 59, 59, ) if False else at(11, 59, 30), at(12, 30))]
        self.assertTrue(hour_has_recording(clips, DAY, 9))
        self.assertFalse(hour_has_recording(clips, DAY, 10))
        self.assertTrue(hour_has_recording(clips, DAY, 11))
        self.assertFalse(hour_has_recording(clips, DAY, 9, now=at(9, 30)))  # aún no había grabado nada

    def test_output_name(self) -> None:
        self.assertEqual(output_name(1, DAY, [8, 9, 10]), "CAM1_2026-09-21_08h-11h.mp4")
        self.assertEqual(output_name(3, DAY, [8, 9, 14, 15]), "CAM3_2026-09-21_08h-10h_14h-16h.mp4")
        self.assertEqual(output_name(2, DAY, [23]), "CAM2_2026-09-21_23h-24h.mp4")
        self.assertEqual(output_name(2, DAY, [1, 3, 5, 7, 9]), "CAM2_2026-09-21_01h-10h_5-bloques.mp4")

    def test_plan_totals_per_channel(self) -> None:
        clips = {1: [clip(at(9), at(9, 40))], 2: [clip(at(9, 20), at(10), 2)]}
        spec = HoursSpec(DAY, {1: [9], 2: [9]}, Path("/tmp/x"), clips, at(12))
        first, second = plan(spec, 600)
        self.assertEqual((first.channel, first.video_seconds, first.gap_seconds), (1, 2400, 0))  # sin negro al final (nada más grabado)
        self.assertEqual((second.video_seconds, second.gap_seconds), (2400, 1200))  # 20 min de negro al principio
        self.assertEqual(second.total_seconds, 3600)
        self.assertGreater(second.estimated_bytes, 0)

    def test_gap_command_draws_the_notice_and_the_running_clock_at_the_channels_size(self) -> None:
        command = gap_command("ffmpeg", "/fonts/x.ttf", Path("/tmp/gap.ts"), (960, 1080), at(11, 41, 30), 10.0)
        joined = " ".join(command)
        self.assertIn("s=960x1080", joined)
        self.assertIn("Grabación no disponible", joined)
        self.assertIn("localtime", joined)
        self.assertIn(str(int(at(11, 41, 30).timestamp())), joined)
        self.assertIn("mpegts", joined)
        self.assertNotIn("-vf", gap_command("ffmpeg", None, Path("/tmp/gap.ts"), (960, 1080), at(11), 5.0))  # sin tipografía: negro liso


@unittest.skipUnless(FFMPEG and shutil.which("ffprobe"), "hace falta ffmpeg")
class EngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.folder = self.tmp / "out"
        self.calls: list[tuple] = []
        self.in_flight = 0
        self.max_in_flight = 0
        self.lock = threading.Lock()
        self.fail_starts: set[datetime] = set()
        self.delay = 0.0
        patcher = mock.patch.object(export_hours, "CHUNK_RETRY_DELAYS", (0.01, 0.01))
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(export_hours, "STATS_POLL_SECONDS", 0.0)
        patcher.start()
        self.addCleanup(patcher.stop)

    # -- DVR falso: video H.264 real de la duración pedida ------------------------------------------

    def make_video(self, seconds: float) -> Path:
        path = self.tmp / f"src_{time.monotonic_ns()}.dav"
        subprocess.run(
            [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size=96x64:rate=10:duration={seconds}",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "10", "-f", "mpegts", str(path)],
            check=True,
        )
        return path

    def submit(self, host, user, password, channel, start, end, priority, stop, progress=None) -> Future:
        self.calls.append((channel, start, end, priority))
        future: Future = Future()
        with self.lock:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)

        def work() -> None:
            try:
                if progress:
                    progress(0)
                if self.delay:
                    stop.wait(self.delay)
                if stop.is_set() or start in self.fail_starts:
                    future.set_result(None)
                    return
                video = self.make_video((end - start).total_seconds())
                if progress:
                    progress(video.stat().st_size)
                future.set_result(video)
            finally:
                with self.lock:
                    self.in_flight -= 1

        threading.Thread(target=work, daemon=True).start()
        return future

    def run_export(self, spec: HoursSpec, timeout: float = 90.0, **kwargs) -> tuple[object, list[tuple]]:
        kwargs.setdefault("stats", lambda: {"live_holders": 0})
        handle = start_hours_export("dvr", "u", "p", spec, submit=self.submit, ffmpeg=FFMPEG, chunk_seconds=4, **kwargs)
        events, deadline = [], time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                event = handle.events.get(timeout=0.2)
            except Exception:
                continue
            events.append(event)
            if event[0] == "finished":
                break
        return handle, events

    def spec(self, cells=None, clips=None, now=None) -> HoursSpec:
        clips = clips or {1: [clip(at(9, 0, 0), at(9, 0, 4)), clip(at(9, 0, 8), at(9, 0, 12))]}
        return HoursSpec(DAY, cells or {1: [9]}, self.folder, clips, now or at(9, 0, 12))

    def leftovers(self) -> list[str]:
        return sorted(p.name for p in self.folder.iterdir() if p.name.startswith("."))

    # -- pruebas ------------------------------------------------------------------------------------

    def test_one_channel_becomes_one_mp4_with_the_gap_filled_by_black_frames_with_text(self) -> None:
        _handle, events = self.run_export(self.spec())
        done = [e for e in events if e[0] == "channel_done"]
        self.assertEqual(len(done), 1)
        path = Path(done[0][2])
        self.assertEqual(path.name, "CAM1_2026-09-21_09h-10h.mp4")
        self.assertIn("1 tramo sin grabación", done[0][3])
        self.assertEqual(events[-1], ("finished", {1: str(path)}))
        duration = export_hours.media_duration(path)
        self.assertAlmostEqual(duration, 12.0, delta=1.0)  # 4 s de video + 4 de negro + 4 de video
        # 4 s a 10 cuadros + 4 s a 1 cuadro + 4 s a 10 cuadros
        capture = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
        frames = []
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            frames.append(float(frame.mean()))
        capture.release()
        self.assertEqual(len(frames), 40 + 4 + 40)
        self.assertTrue(all(value > 100 for value in frames[:40]))  # el video (cuadro de prueba, claro)
        self.assertTrue(all(value < 40 for value in frames[40:44]))  # los cuadros del tramo negro (con el texto encima)
        self.assertTrue(all(value > 100 for value in frames[44:]))  # y el video vuelve
        self.assertEqual(export_hours.video_size(path), (96, 64))  # el negro tiene la resolución del canal

    def test_downloads_are_background_priority_and_only_one_is_in_flight(self) -> None:
        _handle, events = self.run_export(self.spec(clips={1: [clip(at(9, 0, 0), at(9, 0, 20))]}, now=at(9, 0, 20)))
        self.assertEqual(len(self.calls), 5)  # 20 s en trozos de 4
        self.assertTrue(all(call[3] == DownloadPriority.BACKGROUND for call in self.calls))
        self.assertEqual(self.max_in_flight, 1)
        self.assertEqual([call[1] for call in self.calls], [at(9, 0, 4 * i) for i in range(5)])

    def test_progress_and_pieces_are_reported_with_their_index(self) -> None:
        _handle, events = self.run_export(self.spec())
        plan_event = next(e for e in events if e[0] == "plan")
        self.assertEqual(plan_event[1:], (1, 3, 12.0, 8.0, 4.0))
        self.assertEqual([e[2] for e in events if e[0] == "piece"], [0, 2])  # las piezas de video (la 1 es el hueco)
        self.assertTrue(any(e[0] == "progress" and e[2] == 2 and e[3] > 0 for e in events))
        self.assertEqual(sorted(e[2] for e in events if e[0] == "piece_done"), [0, 1, 2])

    def test_no_temporary_files_are_left_behind(self) -> None:
        self.run_export(self.spec())
        self.assertEqual(self.leftovers(), [])
        self.assertEqual(len(list(self.folder.glob("*.mp4"))), 1)

    def test_a_chunk_that_never_downloads_is_retried_then_filled_with_black_and_reported(self) -> None:
        self.fail_starts = {at(9, 0, 8)}
        _handle, events = self.run_export(self.spec())
        retries = [c for c in self.calls if c[1] == at(9, 0, 8)]
        self.assertEqual(len(retries), 1 + export_hours.CHUNK_RETRIES)
        warnings = [e for e in events if e[0] == "warning"]
        self.assertEqual(len(warnings), 1)
        self.assertIn("09:00:08", warnings[0][2])
        done = next(e for e in events if e[0] == "channel_done")
        self.assertIn("no se pudo descargar", done[3])
        self.assertAlmostEqual(export_hours.media_duration(Path(done[2])), 12.0, delta=1.0)

    def test_several_channels_are_exported_one_after_another_each_in_its_own_file(self) -> None:
        clips = {1: [clip(at(9, 0, 0), at(9, 0, 8), 1)], 2: [clip(at(9, 0, 0), at(9, 0, 8), 2)]}
        _handle, events = self.run_export(self.spec(cells={1: [9], 2: [9]}, clips=clips, now=at(9, 0, 8)))
        done = [e for e in events if e[0] == "channel_done"]
        self.assertEqual([e[1] for e in done], [1, 2])
        self.assertEqual(sorted(p.name for p in self.folder.glob("*.mp4")), ["CAM1_2026-09-21_09h-10h.mp4", "CAM2_2026-09-21_09h-10h.mp4"])
        self.assertEqual([c[0] for c in self.calls], [1, 1, 2, 2])  # canal por canal, no a la vez

    def test_cancelling_keeps_finished_channels_and_leaves_nothing_of_the_one_in_progress(self) -> None:
        clips = {1: [clip(at(9, 0, 0), at(9, 0, 8), 1)], 2: [clip(at(9, 0, 0), at(9, 0, 8), 2)]}
        spec = self.spec(cells={1: [9], 2: [9]}, clips=clips, now=at(9, 0, 8))
        handle = start_hours_export("dvr", "u", "p", spec, submit=self._slow_second_channel, ffmpeg=FFMPEG, chunk_seconds=4,
                                    stats=lambda: {"live_holders": 0})
        events = []
        cancelled = False
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                event = handle.events.get(timeout=0.2)
            except Exception:
                continue
            events.append(event)
            if event[0] == "piece" and event[1] == 2 and not cancelled:
                handle.cancel()  # ya arrancó el canal 2
                cancelled = True
            if event[0] == "finished":
                break
        self.assertIn(("channel_failed", 2, "Cancelado"), events)
        finished = events[-1]
        self.assertIsNotNone(finished[1][1])  # el canal 1 se conserva
        self.assertIsNone(finished[1][2])
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), ["CAM1_2026-09-21_09h-10h.mp4"])  # ni parciales ni temporales

    def _slow_second_channel(self, host, user, password, channel, start, end, priority, stop, progress=None) -> Future:
        self.delay = 30.0 if channel == 2 else 0.0
        return self.submit(host, user, password, channel, start, end, priority, stop, progress)

    def test_cancelling_before_starting_marks_every_channel_cancelled(self) -> None:
        self.delay = 30.0
        spec = self.spec()
        handle = start_hours_export("dvr", "u", "p", spec, submit=self.submit, ffmpeg=FFMPEG, chunk_seconds=4, stats=lambda: None)
        time.sleep(0.3)
        handle.cancel()
        events = []
        while not events or events[-1][0] != "finished":
            events.append(handle.events.get(timeout=30))
        self.assertIn(("channel_failed", 1, "Cancelado"), events)
        self.assertEqual(self.leftovers(), [])
        self.assertEqual(list(self.folder.glob("*.mp4")), [])

    def test_a_live_view_pauses_the_downloads_and_the_export_says_so_then_resumes(self) -> None:
        state = {"live": 1}
        self.delay = 0.0
        real_submit = self.submit

        def held_submit(*args, **kwargs):
            def release():
                time.sleep(0.8)
                state["live"] = 0

            threading.Thread(target=release, daemon=True).start()
            return real_submit(*args, **kwargs)

        with mock.patch.object(self, "submit", held_submit):
            spec = self.spec(clips={1: [clip(at(9, 0, 0), at(9, 0, 4))]}, now=at(9, 0, 4))
            handle = start_hours_export("dvr", "u", "p", spec, submit=held_submit, ffmpeg=FFMPEG, chunk_seconds=4,
                                        stats=lambda: {"live_holders": state["live"]})
            events = []
            while not events or events[-1][0] != "finished":
                events.append(handle.events.get(timeout=30))
        paused = [e[1] for e in events if e[0] == "paused"]
        self.assertEqual(paused[:1], [True])
        self.assertIn(False, paused)

    def test_without_ffmpeg_every_channel_fails_with_a_clear_message(self) -> None:
        with mock.patch.object(export_hours, "find_ffmpeg", return_value=None):
            handle = start_hours_export("dvr", "u", "p", self.spec(), submit=self.submit, ffmpeg=None, stats=lambda: None)
            events = []
            while not events or events[-1][0] != "finished":
                events.append(handle.events.get(timeout=10))
        self.assertTrue(any(e[0] == "channel_failed" and "ffmpeg" in e[2] for e in events))
        self.assertEqual(self.calls, [])

    def test_a_channel_without_recordings_in_the_chosen_hours_fails_without_touching_the_dvr(self) -> None:
        spec = self.spec(cells={1: [15]})  # todo lo grabado es de las 09
        _handle, events = self.run_export(spec)
        self.assertTrue(any(e[0] == "channel_failed" and "No hay grabaciones" in e[2] for e in events))
        self.assertEqual(self.calls, [])

    def test_without_a_font_the_gaps_are_plain_black_and_a_warning_is_sent(self) -> None:
        with mock.patch.object(export_hours, "find_font", return_value=None):
            _handle, events = self.run_export(self.spec())
        self.assertTrue(any(e[0] == "warning" and "tipografía" in e[2] for e in events))
        self.assertTrue(any(e[0] == "channel_done" for e in events))


if __name__ == "__main__":
    unittest.main()
