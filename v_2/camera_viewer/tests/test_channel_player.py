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
from camera_viewer.channel_player import (  # noqa: E402
    ChannelPlayer,
    PlayerDeps,
    _ChunkReader,
    chunk_end_for,
    chunk_start_for,
)
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


class ChunkStartTests(unittest.TestCase):
    def test_mirror_of_chunk_end(self) -> None:
        clip_start = T0
        self.assertEqual(chunk_start_for(T0 + timedelta(seconds=100), clip_start, True), T0 + timedelta(seconds=85))
        self.assertEqual(chunk_start_for(T0 + timedelta(seconds=100), clip_start, False), T0 + timedelta(seconds=60))
        self.assertEqual(chunk_start_for(T0 + timedelta(seconds=120), clip_start, False), T0 + timedelta(seconds=60))
        self.assertEqual(chunk_start_for(T0 + timedelta(seconds=30), clip_start, False), T0)  # tope: inicio del clip


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
        patch = mock.patch.object(
            channel_player,
            "chunk_start_for",
            lambda end, clip_start, first: max(end - timedelta(seconds=3 if first else 4), clip_start),
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


def make_video(frames: int, first_index: int = 0) -> tuple[Path, cv2.VideoCapture]:  # (ruta, captura)
    path = Path(tempfile.mkdtemp()) / "v.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (64, 48))
    for i in range(frames):
        writer.write(encode_index(first_index + i))
    writer.release()
    return path, cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)


def index_of(frame) -> int:
    return round(decode_seconds(frame) * FPS)


class ChunkReaderTests(unittest.TestCase):
    def test_forward_reads_every_frame_in_order_then_ends(self) -> None:
        path, capture = make_video(40)
        reader = _ChunkReader(capture, 40, str(path))
        self.addCleanup(reader.close)
        seen = []
        while True:
            ok, frame = reader.read(True)
            if not ok:
                break
            seen.append(index_of(frame))
        self.assertEqual(seen, list(range(40)))

    def test_reverse_reads_every_frame_backwards_across_blocks(self) -> None:
        patch = mock.patch.object(channel_player, "REVERSE_BLOCK_FRAMES", 12)  # varios bloques en 40 cuadros
        patch.start()
        self.addCleanup(patch.stop)
        path, capture = make_video(40)
        reader = _ChunkReader(capture, 40, str(path))
        self.addCleanup(reader.close)
        reader.reverse = True
        reader.seek(39)
        seen = []
        while True:
            ok, frame = reader.read(True)
            if not ok:
                break
            seen.append(index_of(frame))
        self.assertEqual(seen, list(range(39, -1, -1)))  # 40 cuadros en bloques de 12, 12, 12 y 4

    def test_seek_in_both_directions(self) -> None:
        path, capture = make_video(60)
        reader = _ChunkReader(capture, 60, str(path))
        self.addCleanup(reader.close)
        reader.seek(25)
        self.assertEqual([index_of(reader.read(True)[1]) for _ in range(3)], [25, 26, 27])
        reader.set_reverse(True)
        reader.seek(10)
        self.assertEqual([index_of(reader.read(True)[1]) for _ in range(3)], [10, 9, 8])

    def test_switching_direction_never_repeats_or_skips_a_frame(self) -> None:
        path, capture = make_video(60)
        reader = _ChunkReader(capture, 60, str(path))
        self.addCleanup(reader.close)
        reader.seek(20)
        forward = [index_of(reader.read(True)[1]) for _ in range(5)]  # 20..24
        reader.set_reverse(True)
        backward = [index_of(reader.read(True)[1]) for _ in range(6)]  # 23..18
        reader.set_reverse(False)
        onward = [index_of(reader.read(True)[1]) for _ in range(3)]  # 19, 20, 21
        self.assertEqual(forward, [20, 21, 22, 23, 24])
        self.assertEqual(backward, [23, 22, 21, 20, 19, 18])
        self.assertEqual(onward, [19, 20, 21])

    def test_reverse_at_the_first_frame_ends(self) -> None:
        path, capture = make_video(20)
        reader = _ChunkReader(capture, 20, str(path))
        self.addCleanup(reader.close)
        reader.reverse = True
        reader.seek(0)
        self.assertTrue(reader.read(True)[0])
        self.assertFalse(reader.read(True)[0])


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
        h.seek(2.0)  # un salto en pausa deja pasar otro cuadro (el del punto nuevo)
        self.assertIsNotNone(h.wait_for_time(2.0))
        time.sleep(0.3)
        self.assertEqual(len(h.frames), 2)  # solo ese: sigue en pausa
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


class ReversePlaybackTests(PlayerTestCase):
    def reverse_harness(self, **kwargs) -> Harness:
        h = self.harness(**kwargs)
        h.control.set_reverse(True)
        return h

    def test_plays_backwards_frame_by_frame_across_chunk_boundaries(self) -> None:
        h = self.reverse_harness()
        h.start(9.0)
        h.wait_frames(150, 15)  # 5 s hacia atrás: cruza 2 bloques
        times = h.frames[:150]
        self.assertAlmostEqual(times[0], 9.0, delta=0.1)
        self.assertEqual({round((b - a) * FPS) for a, b in zip(times, times[1:])}, {-1})
        self.assertIn("Reversa x1", h.statuses)

    def test_reverse_downloads_a_short_chunk_ending_at_the_position_and_prefetches_the_previous_one(self) -> None:
        h = self.reverse_harness()
        h.start(9.0)
        h.wait_frames(3)
        time.sleep(0.4)
        interactive = h.interactive_submits()[0]
        self.assertEqual(interactive[:2], (T0 + timedelta(seconds=6), T0 + timedelta(seconds=9)))
        by_start = {s[0]: s[2] for s in h.submits}
        self.assertEqual(by_start[T0 + timedelta(seconds=2)], DownloadPriority.PREFETCH)  # el de atrás, con prioridad
        self.assertEqual(by_start[T0 + timedelta(seconds=9)], DownloadPriority.BACKGROUND)  # el de adelante, de reserva

    def test_reverse_reaches_the_start_of_the_segment_then_waits_for_a_seek(self) -> None:
        h = self.reverse_harness()
        h.start(2.0)
        deadline = time.monotonic() + 8
        while "Inicio de segmento" not in h.statuses and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertIn("Inicio de segmento", h.statuses)
        self.assertTrue(h.thread.is_alive())
        h.seek(5.0)
        self.assertIsNotNone(h.wait_for_time(5.0))

    def test_switching_to_reverse_and_back_in_the_middle_is_continuous(self) -> None:
        h = self.harness()
        h.start(2.0)
        h.wait_frames(20)
        h.control.set_reverse(True)
        h.wait_frames(len(h.frames) + 20)
        h.control.set_reverse(False)
        h.wait_frames(len(h.frames) + 20)
        steps = [round((b - a) * FPS) for a, b in zip(h.frames, h.frames[1:])]
        self.assertEqual(set(steps), {1, -1})
        self.assertNotIn(0, steps)  # ningún cuadro repetido al cambiar de sentido
        self.assertTrue(all(abs(s) == 1 for s in steps))

    def test_reverse_with_seek_and_pause(self) -> None:
        h = self.reverse_harness()
        h.start(9.0)
        h.wait_frames(5)
        h.seek(4.0)
        self.assertIsNotNone(h.wait_for_time(4.0))
        h.control.set_paused(True)
        time.sleep(0.3)
        frozen = len(h.frames)
        time.sleep(0.4)
        self.assertEqual(len(h.frames), frozen)
        h.seek(3.0)
        time.sleep(0.5)
        self.assertEqual(len(h.frames), frozen + 1)
        self.assertAlmostEqual(h.frames[-1], 3.0, delta=0.1)

    def test_double_speed_reverse_goes_back_twice_as_fast_and_paints_about_30_fps(self) -> None:
        h = self.reverse_harness()
        h.control.set_speed(2.0)
        h.start(30.0)
        h.wait_frames(2)
        h.frames.clear()
        started = time.monotonic()
        time.sleep(2.0)
        elapsed = time.monotonic() - started
        self.assertLess(len(h.frames) / elapsed, 36)
        self.assertGreater(len(h.frames) / elapsed, 24)
        self.assertGreater((h.frames[0] - h.frames[-1]) / elapsed, 1.8)  # el video retrocede al doble


if __name__ == "__main__":
    unittest.main()
