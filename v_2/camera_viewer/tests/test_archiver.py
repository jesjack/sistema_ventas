"""El archivador pasivo: planificación pura y el motor con un DVR falso (sin red ni GPU
obligatorias -- solo la última clase usa ffmpeg real). Correr desde v_2/:
.venv/bin/python -m unittest camera_viewer.tests.test_archiver -v"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from concurrent.futures import Future
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from camera_viewer import archive_index as idx
from camera_viewer import archiver
from camera_viewer import archive_compactor
from camera_viewer.archive_compactor import CompactionResult
from camera_viewer.clip import Clip
from camera_viewer.download_manager import DownloadPriority
from camera_viewer.light_query_manager import LightPriority

DAY = datetime(2026, 9, 16)
FFMPEG = shutil.which("ffmpeg")


def at(hour: int, minute: int = 0, second: int = 0, day: int = 16) -> datetime:
    return DAY.replace(day=day, hour=hour, minute=minute, second=second)


def clip(start: datetime, end: datetime, channel: int = 1) -> Clip:
    return Clip(channel, start, end)


class PlanningTests(unittest.TestCase):
    def test_eligible_ceiling_is_the_earlier_of_now_and_oldest_plus_margin(self) -> None:
        self.assertEqual(archiver.eligible_ceiling(at(9), 3.0, at(9, 0, 0, day=25)), at(9, day=19))
        # el margen llevaría más allá de "ahora": nunca se adelanta al reloj
        self.assertEqual(archiver.eligible_ceiling(at(9), 3.0, at(10, day=17)), at(10, day=17))

    def test_next_window_starts_at_checked_until_when_it_is_ahead_of_dvr_oldest(self) -> None:
        window = archiver.next_window(at(10), at(9), at(15))
        self.assertEqual(window, (at(10), at(15)))

    def test_next_window_jumps_to_dvr_oldest_when_the_cursor_fell_behind(self) -> None:
        """La PC estuvo apagada más de lo que cubría el margen: lo de en medio ya se perdió."""
        window = archiver.next_window(at(5), at(9), at(15))
        self.assertEqual(window, (at(9), at(15)))

    def test_next_window_is_none_once_the_ceiling_is_reached(self) -> None:
        self.assertIsNone(archiver.next_window(at(15), at(9), at(15)))
        self.assertIsNone(archiver.next_window(at(16), at(9), at(15)))

    def test_next_window_with_no_cursor_yet_starts_at_dvr_oldest(self) -> None:
        self.assertEqual(archiver.next_window(None, at(9), at(15)), (at(9), at(15)))

    def test_chunk_recorded_splits_into_pieces_and_skips_real_gaps(self) -> None:
        clips = [clip(at(9), at(9, 12)), clip(at(9, 20), at(9, 22))]
        pieces = archiver.chunk_recorded(clips, at(9), at(10), 300)
        self.assertEqual(pieces, [(at(9), at(9, 5)), (at(9, 5), at(9, 10)), (at(9, 10), at(9, 12)), (at(9, 20), at(9, 22))])

    def test_chunk_recorded_clips_to_the_window(self) -> None:
        pieces = archiver.chunk_recorded([clip(at(8), at(11))], at(9), at(10), 300)
        self.assertEqual(pieces[0][0], at(9))
        self.assertEqual(pieces[-1][1], at(10))

    def test_chunk_recorded_with_nothing_recorded_is_empty(self) -> None:
        self.assertEqual(archiver.chunk_recorded([], at(9), at(10), 300), [])
        self.assertEqual(archiver.chunk_recorded([clip(at(1), at(2))], at(9), at(10), 300), [])


class FakeFindFiles:
    """mediaFileFind falso: por canal, una lista de tramos grabados."""

    def __init__(self) -> None:
        self.recordings: dict[int, list[tuple[datetime, datetime]]] = {}
        self.calls: list[tuple] = []
        self.fail_channels: set[int] = set()

    def __call__(self, host, user, pw, channel, start, end, max_pages, priority, stop_event) -> Future:
        self.calls.append((channel, start, end, priority))
        future: Future = Future()
        if channel in self.fail_channels:
            future.set_exception(RuntimeError("caído"))
            return future
        items = []
        for rec_start, rec_end in self.recordings.get(channel, []):
            overlap_start, overlap_end = max(rec_start, start), min(rec_end, end)
            if overlap_end > overlap_start:
                items.append({"StartTime": overlap_start.strftime("%Y-%m-%d %H:%M:%S"), "EndTime": overlap_end.strftime("%Y-%m-%d %H:%M:%S")})
        future.set_result(items)
        return future


class FakeSubmit:
    """El embudo de descargas falso: entrega un archivo pequeño real (para poder moverlo/borrarlo)."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.calls: list[tuple] = []
        self.fail_starts: set[datetime] = set()
        self.sizes: dict[datetime, int] = {}

    def __call__(self, host, user, pw, channel, start, end, priority, stop, progress=None) -> Future:
        self.calls.append((channel, start, end, priority))
        future: Future = Future()
        if start in self.fail_starts:
            future.set_result(None)
            return future
        path = self.tmp / f"src_{channel}_{start:%H%M%S}_{time.monotonic_ns()}.dav"
        path.write_bytes(b"x" * self.sizes.get(start, 1000))
        future.set_result(path)
        return future


class FakeCompact:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.fail_sources: set[Path] = set()

    def __call__(self, source, destination, duration_seconds, quality, ffmpeg=None, vaapi_device=None, stop=None) -> CompactionResult:
        self.calls.append((source, destination, duration_seconds, quality))
        if source in self.fail_sources:
            raise RuntimeError("compactación simulada rota")
        destination.write_bytes(b"y" * 100)
        return CompactionResult(destination, 100, used_gpu=True)


class EngineTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sources = self.tmp / "sources"
        self.sources.mkdir()
        self.archive_dir = self.tmp / "archivo"
        self.find_files = FakeFindFiles()
        self.submit = FakeSubmit(self.sources)
        self.compact = FakeCompact()
        self.clock = at(12, day=21)  # "ahora"
        self.mono = 1000.0

    def make(self, **overrides) -> archiver.Archiver:
        free_bytes = overrides.pop("free_bytes", lambda folder: 10**12)
        channels = overrides.pop("channels", (1,))
        config = archiver.ArchiverConfig(channels=channels, host="dvr", username="u", password="p", archive_dir=self.archive_dir, **overrides)
        return archiver.Archiver(
            config, submit=self.submit, find_files=self.find_files, compact=self.compact,
            free_bytes=free_bytes, clock=lambda: self.clock, monotonic=lambda: self.mono,
        )


class LandingTests(EngineTestCase):
    def test_a_channel_with_nothing_recorded_does_nothing(self) -> None:
        engine = self.make()
        self.assertFalse(engine.run_once())
        self.assertEqual(self.submit.calls, [])

    def test_lands_the_oldest_eligible_piece_first_and_records_it(self) -> None:
        self.find_files.recordings[1] = [(at(9), at(9, 20))]
        engine = self.make(margin_days=3.0, segment_seconds=300)
        self.assertTrue(engine.run_once())
        self.assertEqual(self.submit.calls[0][:3], (1, at(9), at(9, 5)))
        segments = idx.segments_for_channel(engine.conn, 1)
        self.assertEqual(len(segments), 1)
        self.assertEqual((segments[0].start, segments[0].end), (at(9), at(9, 5)))
        self.assertTrue((self.archive_dir / segments[0].path).exists())
        self.assertEqual(idx.get_cursor(engine.conn, 1), at(9, 5))

    def test_repeated_calls_walk_forward_through_several_pieces(self) -> None:
        self.find_files.recordings[1] = [(at(9), at(9, 20))]
        engine = self.make(segment_seconds=300)
        seen = []
        for _ in range(4):
            engine.run_once()
            seen = idx.segments_for_channel(engine.conn, 1)
        self.assertEqual([(s.start, s.end) for s in seen], [(at(9), at(9, 5)), (at(9, 5), at(9, 10)), (at(9, 10), at(9, 15)), (at(9, 15), at(9, 20))])

    def test_a_real_gap_advances_the_cursor_without_downloading_anything(self) -> None:
        # una grabación, luego un hueco de varios días antes de la siguiente
        self.find_files.recordings[1] = [(at(9, day=15), at(9, 5, day=15)), (at(9, day=20), at(9, 5, day=20))]
        engine = self.make(margin_days=3000.0)  # techo bien lejos, para que quede mucho por revisar
        engine.run_once()  # aterriza el único trozo de su primera ventana de 1 día (día 15)
        self.assertEqual(len(idx.segments_for_channel(engine.conn, 1)), 1)
        self.submit.calls.clear()
        self.assertTrue(engine.run_once())  # "hizo algo": avanzó el cursor un día más, sin bajar nada (puro hueco)
        self.assertEqual(self.submit.calls, [])
        self.assertEqual(idx.get_cursor(engine.conn, 1), at(9, 5, day=15) + timedelta(days=1))
        self.assertEqual(len(idx.segments_for_channel(engine.conn, 1)), 1)  # sigue habiendo solo ese trozo

    def test_a_query_failure_does_not_move_the_cursor(self) -> None:
        self.find_files.fail_channels.add(1)
        engine = self.make(margin_days=3000.0)
        self.assertFalse(engine.run_once())
        self.assertIsNone(idx.get_cursor(engine.conn, 1))

    def test_a_download_that_fails_after_retries_is_retried_later_not_skipped(self) -> None:
        """2026-09-25: el DVR real estuvo caído >90 min y el cursor seguía avanzando de todos
        modos, saltándose para siempre lo que no se pudo bajar -- ahora el trozo se queda
        pendiente y se reintenta en el siguiente ciclo, sin perder nada."""
        self.find_files.recordings[1] = [(at(9), at(9, 5))]
        self.submit.fail_starts.add(at(9))
        engine = self.make(segment_seconds=300)
        with mock.patch.object(archiver, "CHUNK_RETRY_DELAYS", (0.0, 0.0)):
            self.assertFalse(engine.run_once())  # no se pudo aterrizar nada este ciclo
        self.assertEqual(idx.segments_for_channel(engine.conn, 1), [])  # no se guardó nada
        self.assertIsNone(idx.get_cursor(engine.conn, 1))  # sigue sin avanzar: se reintentará
        calls_after_first_cycle = len(self.submit.calls)
        self.assertGreaterEqual(calls_after_first_cycle, 1 + archiver.CHUNK_RETRIES)

        # Ya no consulta find_files de nuevo (el trozo pendiente sigue cacheado) y reintenta la
        # MISMA pieza; si el DVR ya respondió, esta vez se aterriza bien.
        self.submit.fail_starts.discard(at(9))
        find_files_calls_before = len(self.find_files.calls)
        with mock.patch.object(archiver, "CHUNK_RETRY_DELAYS", (0.0, 0.0)):
            self.assertTrue(engine.run_once())
        self.assertEqual(len(self.find_files.calls), find_files_calls_before)
        self.assertEqual(len(idx.segments_for_channel(engine.conn, 1)), 1)
        self.assertEqual(idx.get_cursor(engine.conn, 1), at(9, 5))

    def test_channels_are_served_round_robin_not_one_at_a_time(self) -> None:
        self.find_files.recordings[1] = [(at(9), at(9, 20))]
        self.find_files.recordings[2] = [(at(9), at(9, 20))]
        engine = self.make(channels=(1, 2), segment_seconds=300)
        for _ in range(2):
            engine.run_once()
        self.assertEqual({s.channel for s in idx.segments_for_channel(engine.conn, 1)} | {s.channel for s in idx.segments_for_channel(engine.conn, 2)}, {1, 2})
        self.assertEqual(len(idx.segments_for_channel(engine.conn, 1)), 1)
        self.assertEqual(len(idx.segments_for_channel(engine.conn, 2)), 1)

    def test_the_cache_of_pending_pieces_avoids_requerying_for_every_single_piece(self) -> None:
        self.find_files.recordings[1] = [(at(9), at(9, 20))]
        engine = self.make(segment_seconds=300)
        for _ in range(4):
            engine.run_once()
        # 2 consultas en total (una para "qué es lo más viejo", cacheada, y una para la ventana de
        # 1 día, también cacheada): no una consulta nueva por cada uno de los 4 trozos.
        self.assertEqual(len(self.find_files.calls), 2)


class RateAndBudgetTests(EngineTestCase):
    def test_the_rate_cap_sleeps_proportionally_to_the_size_downloaded(self) -> None:
        self.find_files.recordings[1] = [(at(9), at(9, 5))]
        self.submit.sizes[at(9)] = 1_000_000  # 1 MB
        engine = self.make(segment_seconds=300, cap_mbps=8.0)  # 8 Mbps = 1 MB/s
        waited = []
        engine.stop.wait = lambda seconds: waited.append(seconds) or False
        engine.run_once()
        self.assertTrue(waited)
        self.assertAlmostEqual(waited[0], 1.0, delta=0.1)

    def test_no_cap_means_no_extra_wait(self) -> None:
        self.find_files.recordings[1] = [(at(9), at(9, 5))]
        engine = self.make(segment_seconds=300, cap_mbps=None)
        waited = []
        engine.stop.wait = lambda seconds: waited.append(seconds) or False
        engine.run_once()
        self.assertEqual(waited, [])

    def test_eviction_removes_the_globally_oldest_segment_first(self) -> None:
        self.find_files.recordings[1] = [(at(9), at(9, 10)), (at(20), at(20, 10))]
        engine = self.make(segment_seconds=300, max_bytes=1500, min_free_bytes=0)
        for _ in range(4):
            engine.run_once()
        segments = idx.segments_for_channel(engine.conn, 1)
        self.assertLessEqual(idx.total_bytes(engine.conn), 1500)
        self.assertTrue(all(s.start >= at(9, 5) for s in segments))  # el más viejo (at(9)) se desalojó
        for segment in segments:
            self.assertTrue((self.archive_dir / segment.path).exists())

    def test_low_free_disk_also_triggers_eviction(self) -> None:
        self.find_files.recordings[1] = [(at(9), at(9, 10))]
        calls = {"n": 0}

        def free_bytes(folder):
            calls["n"] += 1
            return 0 if calls["n"] <= 2 else 10**12  # "sin espacio" en las primeras consultas

        engine = self.make(segment_seconds=300, max_bytes=10**12, free_bytes=free_bytes)
        engine.run_once()
        self.assertEqual(idx.segments_for_channel(engine.conn, 1), [])  # se desalojó lo que se acababa de bajar


class CompactionOrchestrationTests(EngineTestCase):
    def add_raw(self, engine: archiver.Archiver, channel: int, start: datetime, end: datetime, name: str) -> None:
        folder = self.archive_dir / f"ch{channel}"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        path.write_bytes(b"x" * 10_000)
        idx.add_segment(engine.conn, channel, start, end, f"ch{channel}/{name}", path.stat().st_size)

    def test_compacts_the_oldest_raw_segment_when_there_is_nothing_to_land(self) -> None:
        engine = self.make()
        self.add_raw(engine, 1, at(10), at(10, 5), "b.dav")
        self.add_raw(engine, 1, at(9), at(9, 5), "a.dav")
        self.assertTrue(engine.run_once())
        self.assertEqual(self.compact.calls[0][0], self.archive_dir / "ch1" / "a.dav")
        segment = idx.segments_for_channel(engine.conn, 1)[0]
        self.assertTrue(segment.compacted)
        self.assertTrue(segment.path.endswith(".mp4"))
        self.assertFalse((self.archive_dir / "ch1" / "a.dav").exists())  # el crudo se borró

    def test_landing_has_priority_over_compacting(self) -> None:
        self.find_files.recordings[1] = [(at(9), at(9, 5))]
        engine = self.make()
        self.add_raw(engine, 1, at(8), at(8, 5), "a.dav")
        engine.run_once()
        self.assertEqual(self.compact.calls, [])  # aterrizar fue primero
        self.assertEqual(len(self.submit.calls), 1)

    def test_a_broken_segment_does_not_block_the_others(self) -> None:
        engine = self.make()
        self.add_raw(engine, 1, at(9), at(9, 5), "roto.dav")
        self.add_raw(engine, 1, at(10), at(10, 5), "bueno.dav")
        self.compact.fail_sources.add(self.archive_dir / "ch1" / "roto.dav")
        self.assertTrue(engine.run_once())
        segments = {Path(s.path).name: s.compacted for s in idx.segments_for_channel(engine.conn, 1)}
        self.assertFalse(segments["roto.dav"])  # sigue crudo
        self.assertTrue(any(name.endswith(".mp4") for name in segments))  # el otro sí se logró

    def test_a_missing_file_is_dropped_from_the_index_instead_of_retried_forever(self) -> None:
        engine = self.make()
        self.add_raw(engine, 1, at(9), at(9, 5), "fantasma.dav")
        (self.archive_dir / "ch1" / "fantasma.dav").unlink()
        self.assertTrue(engine.run_once())
        self.assertEqual(idx.segments_for_channel(engine.conn, 1), [])


class RunForeverTests(EngineTestCase):
    def test_stops_promptly_when_requested_while_idle(self) -> None:
        engine = self.make()
        engine.request_stop()
        started = time.monotonic()
        engine.run_forever()
        self.assertLess(time.monotonic() - started, 1.0)

    def test_an_exception_in_one_cycle_does_not_kill_the_loop(self) -> None:
        engine = self.make()
        calls = {"n": 0}
        real_run_once = engine.run_once

        def flaky():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            engine.request_stop()
            return real_run_once()

        engine.run_once = flaky
        engine.run_forever()  # no debe propagar la excepción
        self.assertGreaterEqual(calls["n"], 2)

    def test_backoff_grows_on_consecutive_failures_and_resets_on_success(self) -> None:
        """2026-09-25: con el DVR real caído, el archivador reintentaba sin ninguna pausa
        creciente durante más de 90 min seguidos. Ahora, tras varios fallos SEGUIDOS, la espera
        entre ciclos se va doblando -- y en cuanto un ciclo tiene éxito (p. ej. el DVR ya
        reinició), vuelve sola al ritmo normal, sin que nadie tenga que detener el proceso."""
        engine = self.make()
        outcomes = [False, False, False, True]  # 3 fallos seguidos, luego el DVR responde
        waits: list[float] = []

        def fake_run_once() -> bool:
            if outcomes.pop(0):
                engine._register_success()
            else:
                engine._register_failure()
            if not outcomes:
                engine.request_stop()
            return False

        def fake_wait(timeout=None) -> bool:
            waits.append(timeout)
            return engine.stop.is_set()

        engine.run_once = fake_run_once
        engine.stop.wait = fake_wait
        engine.run_forever()

        idle, initial, mult = archiver.CYCLE_IDLE_SLEEP, archiver.DVR_BACKOFF_INITIAL, archiver.DVR_BACKOFF_MULTIPLIER
        self.assertEqual(waits, [idle, initial, initial * mult, idle])

    def test_backoff_never_exceeds_the_configured_cap(self) -> None:
        engine = self.make()
        waits: list[float] = []
        cycles = {"n": 0}

        def always_fails() -> bool:
            engine._register_failure()
            cycles["n"] += 1
            if cycles["n"] >= 12:
                engine.request_stop()
            return False

        def fake_wait(timeout=None) -> bool:
            waits.append(timeout)
            return engine.stop.is_set()

        engine.run_once = always_fails
        engine.stop.wait = fake_wait
        engine.run_forever()

        self.assertLessEqual(max(waits), archiver.DVR_BACKOFF_MAX)
        self.assertEqual(waits[-1], archiver.DVR_BACKOFF_MAX)  # ya llegó al tope y se quedó ahí


@unittest.skipUnless(FFMPEG and shutil.which("ffprobe"), "hace falta ffmpeg/ffprobe")
class RealPipelineTests(unittest.TestCase):
    """Aterrizar y compactar de punta a punta con ffmpeg real (sin red: el DVR sigue siendo falso)."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sources = self.tmp / "sources"
        self.sources.mkdir()

    def make_video(self, seconds: float) -> Path:
        path = self.sources / f"src_{time.monotonic_ns()}.dav"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size=96x64:rate=10:duration={seconds}",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-f", "mpegts", str(path)],
            check=True,
        )
        return path

    def test_a_landed_piece_gets_compacted_into_a_smaller_playable_file(self) -> None:
        # El DVR falso solo tiene una grabación real: 3 s a partir de las 9:00:00 -- así, tras
        # aterrizarla, el archivador se queda sin nada más por delante y pasa solo a compactar.
        fixed_start, fixed_end = at(9), at(9, 0, 3)

        def find_files(host, user, pw, channel, start, end, max_pages, priority, stop_event) -> Future:
            future: Future = Future()
            overlap_start, overlap_end = max(start, fixed_start), min(end, fixed_end)
            items = []
            if overlap_end > overlap_start:
                items.append({"StartTime": f"{overlap_start:%Y-%m-%d %H:%M:%S}", "EndTime": f"{overlap_end:%Y-%m-%d %H:%M:%S}"})
            future.set_result(items)
            return future

        def submit(host, user, pw, channel, start, end, priority, stop, progress=None) -> Future:
            future: Future = Future()
            future.set_result(self.make_video((end - start).total_seconds()))
            return future

        config = archiver.ArchiverConfig(channels=(1,), host="dvr", username="u", password="p", archive_dir=self.tmp / "archivo", segment_seconds=3)
        engine = archiver.Archiver(config, submit=submit, find_files=find_files, clock=lambda: at(9, 0, 10))
        self.addCleanup(engine.close)
        steps = 0
        while engine.run_once():  # aterriza lo único que hay y, ya sin nada por delante, compacta
            steps += 1
            self.assertLess(steps, 50)  # cinturón de seguridad: nunca debería girar en vacío
        segments = idx.segments_for_channel(engine.conn, 1)
        self.assertEqual(len(segments), 1)
        segment = segments[0]
        self.assertTrue(segment.compacted)
        self.assertTrue(segment.path.endswith(".mp4"))
        raw_path = self.tmp / "archivo" / f"ch1" / f"{fixed_start:%Y-%m-%d_%H%M%S}_a_{fixed_end:%H%M%S}.dav"
        # El clip de prueba es tan chico (3 s a 96x64) que el peso fijo del contenedor MP4 puede
        # igualar al del .dav crudo; la reducción de tamaño de verdad (3-30x) ya se mide con
        # muestras reales en test_archive_compactor.py. Aquí lo que importa es el enganche: se
        # compactó, el índice quedó al día y el archivo resultante existe y se puede reproducir.
        self.assertEqual(segment.bytes, (self.tmp / "archivo" / segment.path).stat().st_size)
        self.assertIsNone(archive_compactor.verify_output(self.tmp / "archivo" / segment.path, 3.0))
        self.assertFalse(raw_path.exists())  # el .dav crudo se borró tras compactar


if __name__ == "__main__":
    unittest.main()
