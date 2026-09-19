"""Reproductor de un canal + almacén de bloques, con un DVR falso que genera video
sintético en el que cada cuadro lleva su hora codificada en el color (así se sabe
exactamente qué momento se está mostrando). Correr desde v_2/:
.venv/bin/python -m unittest camera_viewer.tests.test_channel_player -v"""
from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import Future
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from camera_viewer import channel_player  # noqa: E402
from camera_viewer.channel_player import ChannelPlayer, PlayerDeps, chunk_end_for  # noqa: E402
from camera_viewer.chunk_store import ChunkStore  # noqa: E402
from camera_viewer.clip import Clip  # noqa: E402
from camera_viewer.download_manager import DownloadPriority  # noqa: E402
from camera_viewer.playback_control import PAUSED_STATUS, PlaybackControl  # noqa: E402

T0 = datetime(2026, 9, 19, 10, 0, 0)
FPS = 30


def encode_index(index: int) -> np.ndarray:
    """Cuadro plano de 64x48 cuyo color codifica `index` (base 32 en B, G, R)."""
    frame = np.zeros((48, 64, 3), dtype=np.uint8)
    frame[:, :, 0] = (index % 32) * 8
    frame[:, :, 1] = ((index // 32) % 32) * 8
    frame[:, :, 2] = (index // 1024) * 8
    return frame


def decode_seconds(frame: np.ndarray) -> float:
    b, g, r = (int(round(frame[:, :, c].mean() / 8)) for c in range(3))
    return (b + 32 * g + 1024 * r) / FPS


class ChunkEndTests(unittest.TestCase):
    def test_first_chunk_is_15_seconds_and_capped_by_the_clip(self) -> None:
        self.assertEqual(chunk_end_for(T0 + timedelta(seconds=19), T0 + timedelta(hours=1), True), T0 + timedelta(seconds=34))
        self.assertEqual(chunk_end_for(T0 + timedelta(seconds=19), T0 + timedelta(seconds=25), True), T0 + timedelta(seconds=25))

    def test_later_chunks_end_on_the_first_minute_boundary_at_least_20_seconds_away(self) -> None:
        end = T0 + timedelta(hours=1)
        cases = {0: 60, 34: 60, 39: 60, 40: 60, 41: 120, 50: 120}  # segundo de inicio -> segundo de fin
        for start_second, expected in cases.items():
            self.assertEqual(
                chunk_end_for(T0 + timedelta(seconds=start_second), end, False), T0 + timedelta(seconds=expected), start_second
            )
        self.assertEqual(chunk_end_for(T0 + timedelta(seconds=60), end, False), T0 + timedelta(seconds=120))
        self.assertEqual(chunk_end_for(T0 + timedelta(seconds=41), T0 + timedelta(seconds=90), False), T0 + timedelta(seconds=90))


class ChunkStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.store = ChunkStore()

    def file(self, name: str) -> Path:
        path = self.tmp / name
        path.write_bytes(b"x")
        return path

    def at(self, seconds: int) -> datetime:
        return T0 + timedelta(seconds=seconds)

    def test_find_returns_the_chunk_containing_the_moment(self) -> None:
        self.store.add(1, self.at(0), self.at(20), self.file("a"))
        self.store.add(1, self.at(20), self.at(60), self.file("b"))
        self.assertEqual(self.store.find(1, self.at(19)).path.name, "a")
        self.assertEqual(self.store.find(1, self.at(20)).path.name, "b")  # el fin es exclusivo
        self.assertIsNone(self.store.find(1, self.at(60)))
        self.assertIsNone(self.store.find(2, self.at(10)))

    def test_duplicate_range_keeps_the_first_and_deletes_the_extra_file(self) -> None:
        first, second = self.file("a"), self.file("b")
        self.store.add(1, self.at(0), self.at(20), first)
        self.store.add(1, self.at(0), self.at(20), second)
        self.assertTrue(first.exists())
        self.assertFalse(second.exists())

    def test_prune_deletes_only_chunks_entirely_outside_the_window(self) -> None:
        for name, (a, b) in {"old": (0, 20), "edge": (20, 60), "now": (60, 120), "far": (300, 360)}.items():
            self.store.add(1, self.at(a), self.at(b), self.file(name))
        self.store.prune(1, self.at(40), self.at(200))
        self.assertEqual([e.path.name for e in self.store.entries(1)], ["edge", "now"])
        self.assertFalse((self.tmp / "old").exists() or (self.tmp / "far").exists())

    def test_remove_and_clear_delete_files(self) -> None:
        entry = self.store.add(1, self.at(0), self.at(20), self.file("a"))
        self.store.add(1, self.at(20), self.at(40), self.file("b"))
        self.store.remove(entry)
        self.assertFalse((self.tmp / "a").exists())
        self.store.clear()
        self.assertFalse((self.tmp / "b").exists())
        self.assertEqual(self.store.entries(1), [])


class Harness:
    """Un ChannelPlayer con un DVR falso: cada descarga genera un video sintético del rango pedido."""

    def __init__(self, clip_end: datetime | None = None, delay: float = 0.0, fail_first: int = 0) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.store = ChunkStore()
        self.control = PlaybackControl((1,))
        self.submits: list[tuple[datetime, datetime, int, threading.Event]] = []
        self.frames: list[float] = []  # hora (s desde T0) de cada cuadro mostrado
        self.statuses: list[str] = []
        self.semaphore = threading.Semaphore(2)
        self.stop = threading.Event()
        self.delay = delay
        self.fail_first = fail_first
        deps = PlayerDeps(
            store=self.store,
            control=self.control,
            submit=self.submit,
            fetch_clips=lambda *args: [],
            emit_frame=self.on_frame,
            emit_status=lambda channel, text: self.statuses.append(text),
            emit_day_changed=lambda day: None,
        )
        self.player = ChannelPlayer(1, [Clip(1, T0, clip_end or T0 + timedelta(minutes=10))], deps, self.stop, self.semaphore, lambda: True)
        self.thread: threading.Thread | None = None

    def submit(self, channel: int, start: datetime, end: datetime, priority: int, stop: threading.Event) -> Future:
        self.submits.append((start, end, priority, stop))
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
            path = self.tmp / f"{start:%H%M%S}_{end:%H%M%S}_{len(self.submits)}.avi"
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (64, 48))
            first = round((start - T0).total_seconds() * FPS)
            for i in range(round((end - start).total_seconds() * FPS)):
                writer.write(encode_index(first + i))
            writer.release()
            future.set_result(path)

        threading.Thread(target=work, daemon=True).start()
        return future

    def on_frame(self, channel: int, frame: np.ndarray) -> None:
        self.frames.append(decode_seconds(frame))
        self.semaphore.release()  # hace de "la interfaz ya lo mostró"

    def start(self, target_seconds: float, start_delay: float = 0.0) -> None:
        self.thread = threading.Thread(
            target=self.player.run, args=(T0 + timedelta(seconds=target_seconds), start_delay), daemon=True
        )
        self.thread.start()

    def seek(self, seconds: float) -> None:
        self.control.request_seek(T0 + timedelta(seconds=seconds))

    def wait_frames(self, count: int, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while len(self.frames) < count and time.monotonic() < deadline:
            time.sleep(0.01)

    def wait_for_time(self, seconds: float, tolerance: float = 0.1, timeout: float = 5.0) -> float | None:
        """Espera un cuadro cuya hora esté cerca de `seconds` (ignora cuadros viejos aún en vuelo). Devuelve cuánto tardó."""
        started = time.monotonic()
        while time.monotonic() - started < timeout:
            if any(abs(t - seconds) <= tolerance for t in list(self.frames)):
                return time.monotonic() - started
            time.sleep(0.005)
        return None

    def interactive_submits(self) -> list:
        return [s for s in self.submits if s[2] == DownloadPriority.INTERACTIVE]

    def stop_and_join(self) -> None:
        self.stop.set()
        if self.thread:
            self.thread.join(5)


class PlayerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        # Bloques cortos y sin alinear al minuto, para que las pruebas duren segundos.
        patch = mock.patch.object(
            channel_player,
            "chunk_end_for",
            lambda start, clip_end, first: min(start + timedelta(seconds=3 if first else 4), clip_end),
        )
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(channel_player, "CLIP_RETRY_BACKOFF", 0.05)
        patch.start()
        self.addCleanup(patch.stop)

    def harness(self, **kwargs) -> Harness:
        h = Harness(**kwargs)
        self.addCleanup(h.stop_and_join)
        return h


class PlaybackTests(PlayerTestCase):
    def test_plays_from_the_selected_time_in_real_time(self) -> None:
        h = self.harness()
        started = time.monotonic()
        h.start(5.0)
        h.wait_frames(31)
        self.assertAlmostEqual(h.frames[0], 5.0, delta=0.1)
        self.assertAlmostEqual(h.frames[30], 6.0, delta=0.1)
        self.assertGreater(time.monotonic() - started, 0.9)  # a x1: 30 cuadros tardan ~1 s
        self.assertEqual(h.submits[0][2], DownloadPriority.INTERACTIVE)
        self.assertEqual(h.submits[0][:2], (T0 + timedelta(seconds=5), T0 + timedelta(seconds=8)))  # el primero es corto

    def test_crosses_chunks_without_gaps_or_repeats(self) -> None:
        h = self.harness()
        h.start(0.0)
        h.wait_frames(150, 15)  # 5 s: cruza 2 bloques
        times = h.frames[:150]
        steps = {round((b - a) * FPS) for a, b in zip(times, times[1:])}
        self.assertEqual(steps, {1})

    def test_next_chunk_is_prefetched_and_previous_one_in_background(self) -> None:
        h = self.harness()
        h.start(5.0)
        h.wait_frames(2)
        time.sleep(0.3)
        priorities = {s[0]: s[2] for s in h.submits}
        self.assertEqual(priorities[T0 + timedelta(seconds=8)], DownloadPriority.PREFETCH)
        self.assertEqual(priorities[T0], DownloadPriority.BACKGROUND)  # [0, 5): lo de atrás

    def test_seek_inside_the_current_chunk_does_not_download_anything(self) -> None:
        h = self.harness()
        h.start(5.0)
        h.wait_frames(3)
        before = len(h.submits)
        h.seek(7.0)
        self.assertIsNotNone(h.wait_for_time(7.0))
        self.assertEqual(len(h.submits), before)

    def test_seek_back_into_the_prefetched_previous_chunk_is_a_cache_hit(self) -> None:
        h = self.harness()
        h.start(5.0)
        h.wait_frames(3)
        time.sleep(0.4)  # deja que llegue la descarga de lo de atrás
        interactive_before = len(h.interactive_submits())
        h.seek(2.0)
        elapsed = h.wait_for_time(2.0)
        self.assertIsNotNone(elapsed)
        self.assertLess(elapsed, 0.3)  # instantáneo
        self.assertEqual(len(h.interactive_submits()), interactive_before)

    def test_seek_to_an_undownloaded_point_downloads_only_that_short_chunk(self) -> None:
        h = self.harness()
        h.start(0.0)
        h.wait_frames(3)
        h.seek(300.0)
        self.assertIsNotNone(h.wait_for_time(300.0))
        last = h.interactive_submits()[-1]
        self.assertEqual(last[:2], (T0 + timedelta(seconds=300), T0 + timedelta(seconds=303)))

    def test_a_seek_abandons_downloads_that_no_longer_matter(self) -> None:
        h = self.harness(delay=3.0)  # descargas lentas
        h.start(0.0)
        time.sleep(0.3)
        first_request_stop = h.submits[0][3]
        h.seek(300.0)
        time.sleep(0.5)
        self.assertTrue(first_request_stop.is_set())

    def test_pause_freezes_and_resume_continues_without_losing_frames(self) -> None:
        h = self.harness()
        h.start(0.0)
        h.wait_frames(15)
        h.control.set_paused(True)
        time.sleep(0.2)
        frozen = len(h.frames)
        time.sleep(0.5)
        self.assertEqual(len(h.frames), frozen)
        h.control.set_paused(False)
        h.wait_frames(frozen + 30)
        steps = {round((b - a) * FPS) for a, b in zip(h.frames, h.frames[1:])}
        self.assertEqual(steps, {1})

    def test_paused_seek_shows_one_frame_of_the_new_point_and_stays_paused(self) -> None:
        h = self.harness()
        h.start(0.0)
        h.wait_frames(10)
        h.control.set_paused(True)
        time.sleep(0.3)
        h.frames.clear()
        h.seek(2.0)
        time.sleep(0.6)
        self.assertEqual(len(h.frames), 1)
        self.assertAlmostEqual(h.frames[0], 2.0, delta=0.1)
        time.sleep(0.4)
        self.assertEqual(len(h.frames), 1)

    def test_paused_start_shows_the_first_frame_only(self) -> None:
        h = self.harness()
        h.control.reset(paused=True)
        h.start(4.0)
        time.sleep(0.8)
        self.assertEqual(len(h.frames), 1)
        h.control.step()
        time.sleep(0.3)
        self.assertEqual(len(h.frames), 2)
        self.assertIn(PAUSED_STATUS, h.statuses)

    def test_double_speed_advances_twice_as_fast_but_paints_about_30_frames_per_second(self) -> None:
        h = self.harness()
        h.control.set_speed(2.0)
        h.start(0.0)
        h.wait_frames(2)
        h.frames.clear()
        started = time.monotonic()
        time.sleep(2.0)
        elapsed = time.monotonic() - started
        painted_per_second = len(h.frames) / elapsed
        video_seconds_per_second = (h.frames[-1] - h.frames[0]) / elapsed
        self.assertLess(painted_per_second, 36)  # tope de ~30 cuadros por segundo
        self.assertGreater(painted_per_second, 24)
        self.assertGreater(video_seconds_per_second, 1.8)  # pero el video avanza al doble

    def test_end_of_the_segment_waits_for_a_seek_instead_of_dying(self) -> None:
        h = self.harness(clip_end=T0 + timedelta(seconds=8))
        h.start(6.0)
        deadline = time.monotonic() + 8
        while "Fin de segmento" not in h.statuses and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertIn("Fin de segmento", h.statuses)
        self.assertTrue(h.thread.is_alive())
        h.seek(1.0)
        self.assertIsNotNone(h.wait_for_time(1.0))

    def test_no_recording_at_the_time_reports_it_and_waits_for_a_seek(self) -> None:
        h = self.harness()
        h.start(9999.0)  # fuera del clip
        time.sleep(0.4)
        self.assertIn("Sin grabación en esa hora", h.statuses)
        h.seek(2.0)
        self.assertIsNotNone(h.wait_for_time(2.0))

    def test_failed_downloads_are_retried_then_give_up(self) -> None:
        h = self.harness(fail_first=2)
        h.start(0.0)
        h.wait_frames(2)
        self.assertIn("Reintentando descarga (1/3)...", h.statuses)
        self.assertGreaterEqual(h.frames[0], 0.0)

        dead = self.harness(fail_first=99)
        dead.start(0.0)
        deadline = time.monotonic() + 5
        while "No se pudo reproducir la grabación" not in dead.statuses and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertIn("No se pudo reproducir la grabación", dead.statuses)

    def test_cancel_while_paused_or_downloading_returns_promptly(self) -> None:
        h = self.harness()
        h.start(0.0)
        h.wait_frames(5)
        h.control.set_paused(True)
        time.sleep(0.2)
        started = time.monotonic()
        h.stop.set()
        h.thread.join(5)
        self.assertFalse(h.thread.is_alive())
        self.assertLess(time.monotonic() - started, 1.0)

        slow = self.harness(delay=30.0)
        slow.start(0.0)
        time.sleep(0.3)
        started = time.monotonic()
        slow.stop.set()
        slow.thread.join(5)
        self.assertFalse(slow.thread.is_alive())
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertTrue(slow.submits[0][3].is_set())  # la descarga en curso se canceló

    def test_old_chunks_are_pruned_as_playback_moves_on(self) -> None:
        with mock.patch.object(channel_player, "KEEP_BEHIND", timedelta(seconds=2)), mock.patch.object(
            channel_player, "KEEP_AHEAD", timedelta(seconds=6)
        ):
            h = self.harness()
            h.control.set_speed(2.0)
            h.start(0.0)
            h.wait_frames(240, 15)  # ~8 s de video
            starts = [e.start for e in h.store.entries(1)]
            self.assertNotIn(T0, starts)  # lo de hace más de 2 s ya se borró


if __name__ == "__main__":
    unittest.main()
