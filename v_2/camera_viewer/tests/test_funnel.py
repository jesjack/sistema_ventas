"""Pruebas del embudo hacia el DVR con un DVR falso (no tocan el real).
Correr desde v_2/: .venv/bin/python -m unittest camera_viewer.tests.test_funnel -v"""
from __future__ import annotations

import socket
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import requests

from camera_viewer import download_client, download_service
from camera_viewer.download_manager import RecordingDownloadManager
from camera_viewer.light_query_manager import LightPriority, LightQueryCancelled, LightQueryManager

START = datetime(2026, 9, 18, 12, 0, 0)
END = datetime(2026, 9, 18, 12, 0, 45)


class FakeResponse:
    def __init__(self, text: str = "", chunks: list[bytes] | None = None, fail_after_first: bool = False) -> None:
        self.text = text
        self._chunks = chunks or []
        self._fail_after_first = fail_after_first

    def raise_for_status(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None

    def iter_content(self, chunk_size: int = 0):
        for index, chunk in enumerate(self._chunks):
            if self._fail_after_first and index == 1:
                raise requests.exceptions.ConnectionError("cortada a medias")
            yield chunk


def find_page(*starts: str) -> str:
    return "\n".join(
        f"items[{i}].StartTime={s}\nitems[{i}].EndTime={s[:-2]}59" for i, s in enumerate(starts)
    ) or "found=0"


class FakeDVR:
    """requests.get falso: cuenta llamadas y conexiones simultáneas."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.active = 0
        self.max_active = 0
        self.delay = 0.0
        self.handler = None  # url -> FakeResponse | raise
        self.lock = threading.Lock()

    def __call__(self, url: str, **kwargs):
        with self.lock:
            self.calls.append(url)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                time.sleep(self.delay)
            return self.handler(url)
        finally:
            with self.lock:
                self.active -= 1


class LightQueryManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dvr = FakeDVR()
        self.dvr.handler = lambda url: FakeResponse(text="ok")
        patcher = mock.patch.object(requests, "get", self.dvr)
        patcher.start()
        self.addCleanup(patcher.stop)

    def submit_get(self, manager, priority=LightPriority.USER, stop=None, path="cgi-bin/x.cgi?a=1"):
        return manager.submit_get("dvr", "u", "p", path, priority, stop or threading.Event())

    def test_get_returns_text(self) -> None:
        manager = LightQueryManager(threads=1, retry_delay=0)
        self.assertEqual(self.submit_get(manager).result(timeout=5), "ok")
        self.assertEqual(self.dvr.calls, ["http://dvr/cgi-bin/x.cgi?a=1"])

    def test_user_priority_goes_before_periodic(self) -> None:
        manager = LightQueryManager(threads=1, retry_delay=0)
        gate = threading.Event()
        order: list[str] = []

        def handler(url: str):
            if "blocker" in url:
                gate.wait(5)
            order.append(url.rsplit("=", 1)[-1] if "=" in url else url)
            return FakeResponse(text="ok")

        self.dvr.handler = handler
        blocker = self.submit_get(manager, path="blocker")
        time.sleep(0.2)  # el único hilo ya está dentro del bloqueador
        periodic = self.submit_get(manager, LightPriority.PERIODIC, path="p?x=periodic")
        user = self.submit_get(manager, LightPriority.USER, path="u?x=user")
        gate.set()
        for future in (blocker, periodic, user):
            future.result(timeout=5)
        self.assertEqual(order[1:], ["user", "periodic"])

    def test_never_more_than_two_simultaneous(self) -> None:
        manager = LightQueryManager(threads=2, retry_delay=0)
        self.dvr.delay = 0.05
        futures = [self.submit_get(manager, path=f"x?n={n}") for n in range(8)]
        for future in futures:
            future.result(timeout=10)
        self.assertEqual(self.dvr.max_active, 2)

    def test_retries_then_succeeds(self) -> None:
        manager = LightQueryManager(threads=1, max_attempts=3, retry_delay=0.05)
        attempts: list[float] = []

        def handler(url: str):
            attempts.append(time.monotonic())
            if len(attempts) < 3:
                raise requests.exceptions.ReadTimeout("atasco")
            return FakeResponse(text="por fin")

        self.dvr.handler = handler
        self.assertEqual(self.submit_get(manager).result(timeout=5), "por fin")
        self.assertEqual(len(attempts), 3)
        self.assertGreaterEqual(attempts[1] - attempts[0], 0.05)

    def test_fails_after_max_attempts(self) -> None:
        manager = LightQueryManager(threads=1, max_attempts=3, retry_delay=0)
        self.dvr.handler = mock.Mock(side_effect=requests.exceptions.ConnectionError("caído"))
        with self.assertRaises(requests.exceptions.ConnectionError):
            self.submit_get(manager).result(timeout=5)
        self.assertEqual(self.dvr.handler.call_count, 3)

    def test_cancelled_while_waiting_to_retry(self) -> None:
        manager = LightQueryManager(threads=1, max_attempts=3, retry_delay=30)
        self.dvr.handler = mock.Mock(side_effect=requests.exceptions.ConnectionError("caído"))
        stop = threading.Event()
        future = self.submit_get(manager, stop=stop)
        time.sleep(0.2)
        stop.set()
        with self.assertRaises(LightQueryCancelled):
            future.result(timeout=5)

    def test_find_files_collects_pages_and_destroys(self) -> None:
        pages = iter([find_page("2026-09-18 12:00:00", "2026-09-18 12:25:00"), find_page("2026-09-18 12:50:00"), find_page()])

        def handler(url: str):
            if "factory.create" in url:
                return FakeResponse(text="result=7")
            if "findNextFile" in url:
                return FakeResponse(text=next(pages))
            return FakeResponse(text="OK")

        self.dvr.handler = handler
        manager = LightQueryManager(threads=1, retry_delay=0)
        items = manager.submit_find_files("dvr", "u", "p", 3, START, END, 50, LightPriority.USER, threading.Event()).result(timeout=5)
        self.assertEqual([item["StartTime"] for item in items], ["2026-09-18 12:00:00", "2026-09-18 12:25:00", "2026-09-18 12:50:00"])
        self.assertIn("condition.Channel=3", "".join(self.dvr.calls))
        self.assertTrue(self.dvr.calls[-1].endswith("action=destroy&object=7"))

    def test_find_files_single_page_when_max_pages_is_one(self) -> None:
        def handler(url: str):
            if "factory.create" in url:
                return FakeResponse(text="result=1")
            if "findNextFile" in url:
                return FakeResponse(text=find_page("2026-09-18 12:00:00"))
            return FakeResponse(text="OK")

        self.dvr.handler = handler
        manager = LightQueryManager(threads=1, retry_delay=0)
        manager.submit_find_files("dvr", "u", "p", 1, START, END, 1, LightPriority.USER, threading.Event()).result(timeout=5)
        self.assertEqual(sum("findNextFile" in call for call in self.dvr.calls), 1)

    def test_find_files_destroys_object_and_retries_whole_sequence_on_failure(self) -> None:
        state = {"creates": 0}

        def handler(url: str):
            if "factory.create" in url:
                state["creates"] += 1
                return FakeResponse(text=f"result={state['creates']}")
            if "findNextFile" in url:
                if state["creates"] == 1:
                    raise requests.exceptions.ReadTimeout("atasco")
                return FakeResponse(text=find_page("2026-09-18 12:00:00"))
            return FakeResponse(text="OK")

        self.dvr.handler = handler
        manager = LightQueryManager(threads=1, max_attempts=3, retry_delay=0)
        items = manager.submit_find_files("dvr", "u", "p", 1, START, END, 1, LightPriority.USER, threading.Event()).result(timeout=5)
        self.assertEqual(len(items), 1)
        self.assertTrue(any(call.endswith("action=destroy&object=1") for call in self.dvr.calls))
        self.assertTrue(any(call.endswith("action=destroy&object=2") for call in self.dvr.calls))


class RecordingRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.dvr = FakeDVR()
        patcher = mock.patch.object(requests, "get", self.dvr)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch("camera_viewer.download_manager.DOWNLOAD_RETRY_DELAY", 0.05)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.manager = RecordingDownloadManager(max_concurrent=2, download_dir=self.tmp, post_download_gap=0)
        self.addCleanup(self.manager.shutdown)

    def submit(self):
        return self.manager.submit("dvr", "u", "p", 1, START, END, 0, threading.Event())

    def test_connection_error_before_first_byte_is_retried_once(self) -> None:
        attempts = []

        def handler(url: str):
            attempts.append(url)
            if len(attempts) == 1:
                raise requests.exceptions.ConnectionError("reset")
            return FakeResponse(chunks=[b"abc", b"def"])

        self.dvr.handler = handler
        path = self.submit().result(timeout=5)
        self.assertEqual(path.read_bytes(), b"abcdef")
        self.assertEqual(len(attempts), 2)

    def test_second_connection_error_gives_up(self) -> None:
        self.dvr.handler = mock.Mock(side_effect=requests.exceptions.ConnectionError("reset"))
        self.assertIsNone(self.submit().result(timeout=5))
        self.assertEqual(self.dvr.handler.call_count, 2)
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_error_after_first_byte_is_not_retried(self) -> None:
        self.dvr.handler = mock.Mock(return_value=FakeResponse(chunks=[b"abc", b"def"], fail_after_first=True))
        self.assertIsNone(self.submit().result(timeout=5))
        self.assertEqual(self.dvr.handler.call_count, 1)
        self.assertEqual(list(self.tmp.iterdir()), [])


class DownloadProgressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.dvr = FakeDVR()
        patcher = mock.patch.object(requests, "get", self.dvr)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.manager = RecordingDownloadManager(max_concurrent=2, download_dir=self.tmp, post_download_gap=0)
        self.addCleanup(self.manager.shutdown)

    def test_progress_starts_at_zero_when_the_job_leaves_the_queue_then_counts_bytes(self) -> None:
        self.dvr.handler = lambda url: FakeResponse(chunks=[b"abc", b"defg", b"h"])
        seen: list[int] = []
        self.manager.submit("dvr", "u", "p", 1, START, END, 0, threading.Event(), progress=seen.append).result(timeout=5)
        self.assertEqual(seen, [0, 3, 7, 8])

    def test_a_queued_job_reports_nothing_until_it_starts(self) -> None:
        release = threading.Event()
        self.dvr.handler = lambda url: (release.wait(5), FakeResponse(chunks=[b"x"]))[1]
        for _ in range(2):  # ocupan los dos hilos
            self.manager.submit("dvr", "u", "p", 1, START, END, 0, threading.Event())
        seen: list[int] = []
        future = self.manager.submit("dvr", "u", "p", 2, START, END, 0, threading.Event(), progress=seen.append)
        time.sleep(0.3)
        self.assertEqual(seen, [])  # sigue en cola
        release.set()
        future.result(timeout=5)
        self.assertEqual(seen[0], 0)

    def test_a_failing_progress_callback_does_not_break_the_download(self) -> None:
        self.dvr.handler = lambda url: FakeResponse(chunks=[b"abc"])

        def boom(_received: int) -> None:
            raise RuntimeError("callback roto")

        path = self.manager.submit("dvr", "u", "p", 1, START, END, 0, threading.Event(), progress=boom).result(timeout=5)
        self.assertEqual(path.read_bytes(), b"abc")

    def test_a_retry_after_a_connection_error_starts_counting_again_from_zero(self) -> None:
        attempts: list[str] = []

        def handler(url: str):
            attempts.append(url)
            if len(attempts) == 1:
                raise requests.exceptions.ConnectionError("reset")
            return FakeResponse(chunks=[b"abc"])

        self.dvr.handler = handler
        seen: list[int] = []
        with mock.patch("camera_viewer.download_manager.DOWNLOAD_RETRY_DELAY", 0.01):
            self.manager.submit("dvr", "u", "p", 1, START, END, 0, threading.Event(), progress=seen.append).result(timeout=5)
        self.assertEqual(seen, [0, 0, 3])


class CourtesyGapTests(unittest.TestCase):
    """La pausa entre descargas del mismo hilo se respeta también tras una cancelación."""

    GAP = 0.4

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.dvr = FakeDVR()
        patcher = mock.patch.object(requests, "get", self.dvr)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.manager = RecordingDownloadManager(max_concurrent=1, download_dir=self.tmp, post_download_gap=self.GAP)
        self.addCleanup(self.manager.shutdown)
        self.events: list[tuple[str, int, float]] = []

    def response_for(self, channel: int, slow: bool):
        events = self.events

        class Response(FakeResponse):
            def __exit__(self, *exc) -> None:
                events.append(("cierra", channel, time.monotonic()))

            def iter_content(self, chunk_size: int = 0):
                for _ in range(100 if slow else 1):
                    time.sleep(0.02)
                    yield b"x"

        return Response()

    def gap_between(self, cancel_first: bool) -> float:
        def handler(url: str):
            channel = int(url.split("channel=")[1].split("&")[0])
            self.events.append(("abre", channel, time.monotonic()))
            return self.response_for(channel, slow=channel == 1)

        self.dvr.handler = handler
        stop_first = threading.Event()
        self.manager.submit("dvr", "u", "p", 1, START, END, 0, stop_first)
        second = self.manager.submit("dvr", "u", "p", 2, START, END, 0, threading.Event())
        time.sleep(0.2)
        if cancel_first:
            stop_first.set()
        second.result(timeout=10)
        closed = next(t for kind, ch, t in self.events if kind == "cierra" and ch == 1)
        opened = next(t for kind, ch, t in self.events if kind == "abre" and ch == 2)
        return opened - closed

    def test_after_a_download_that_ends_normally_the_next_one_waits_the_gap(self) -> None:
        self.assertGreaterEqual(self.gap_between(cancel_first=False), self.GAP * 0.9)

    def test_after_a_cancelled_download_the_next_one_also_waits_the_gap(self) -> None:
        self.assertGreaterEqual(self.gap_between(cancel_first=True), self.GAP * 0.9)

    def test_a_job_cancelled_before_it_started_does_not_wait_because_it_never_touched_the_dvr(self) -> None:
        release = threading.Event()
        self.dvr.handler = lambda url: (release.wait(5), FakeResponse(chunks=[b"x"]))[1]
        self.manager.submit("dvr", "u", "p", 1, START, END, 0, threading.Event())  # ocupa el hilo
        stop = threading.Event()
        stop.set()
        cancelled = self.manager.submit("dvr", "u", "p", 2, START, END, 0, stop)
        last = self.manager.submit("dvr", "u", "p", 3, START, END, 0, threading.Event())
        release.set()
        started = time.monotonic()
        self.assertIsNone(cancelled.result(timeout=10))
        last.result(timeout=10)
        # dos descargas reales tienen su pausa (la del primero y la de la última), la cancelada antes de empezar no
        self.assertLess(time.monotonic() - started, self.GAP * 2 + 0.6)


class DvrLogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.dvr = FakeDVR()
        patcher = mock.patch.object(requests, "get", self.dvr)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch("camera_viewer.download_manager.DOWNLOAD_RETRY_DELAY", 0.01)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.manager = RecordingDownloadManager(max_concurrent=1, download_dir=self.tmp, post_download_gap=0)
        self.addCleanup(self.manager.shutdown)

    def submit(self, channel: int = 1, stop: threading.Event | None = None):
        return self.manager.submit("dvr", "u", "p", channel, START, END, 2, stop or threading.Event())

    def test_a_good_download_logs_wait_first_byte_total_size_and_attempts(self) -> None:
        self.dvr.handler = lambda url: FakeResponse(chunks=[b"a" * 1000, b"b" * 1000])
        with self.assertLogs("camera_viewer.dvr", level="INFO") as logs:
            self.submit(3).result(timeout=5)
            time.sleep(0.1)
        line = logs.output[0]
        self.assertIn("descarga ch3 12:00:00-12:00:45 prio=2", line)
        for expected in ("OK", "espera_en_cola=", "primer_byte=", "total=", "MB", "Mbps", "intentos=1"):
            self.assertIn(expected, line)

    def test_a_failed_download_is_a_warning_with_the_reason_and_attempts(self) -> None:
        self.dvr.handler = mock.Mock(side_effect=requests.exceptions.ReadTimeout("Read timed out"))
        with self.assertLogs("camera_viewer.dvr", level="INFO") as logs:
            self.assertIsNone(self.submit().result(timeout=5))
            time.sleep(0.1)
        self.assertEqual(logs.records[0].levelname, "WARNING")
        self.assertIn("FALLÓ", logs.output[0])
        self.assertIn("motivo=ReadTimeout", logs.output[0])
        self.assertIn("sin_bytes", logs.output[0])

    def test_a_connection_error_then_success_shows_two_attempts(self) -> None:
        calls = []

        def handler(url: str):
            calls.append(url)
            if len(calls) == 1:
                raise requests.exceptions.ConnectionError("reset")
            return FakeResponse(chunks=[b"abc"])

        self.dvr.handler = handler
        with self.assertLogs("camera_viewer.dvr", level="INFO") as logs:
            self.submit().result(timeout=5)
            time.sleep(0.1)
        self.assertIn("OK", logs.output[0])
        self.assertIn("intentos=2", logs.output[0])

    def test_a_cancelled_download_is_logged_as_cancelled(self) -> None:
        stop = threading.Event()

        class Slow(FakeResponse):
            def iter_content(self, chunk_size: int = 0):
                for _ in range(200):
                    time.sleep(0.02)
                    yield b"x" * 100

        self.dvr.handler = lambda url: Slow()
        with self.assertLogs("camera_viewer.dvr", level="INFO") as logs:
            future = self.submit(stop=stop)
            time.sleep(0.2)
            stop.set()
            self.assertIsNone(future.result(timeout=5))
            time.sleep(0.1)
        self.assertIn("CANCELADA", logs.output[0])

    def test_light_queries_are_only_logged_when_slow_failed_or_retried(self) -> None:
        light = LightQueryManager(threads=1, max_attempts=2, retry_delay=0)
        self.addCleanup(light.shutdown)
        self.dvr.handler = lambda url: FakeResponse(text="ok")
        with self.assertNoLogs("camera_viewer.dvr", level="INFO"):
            light.submit_get("dvr", "u", "p", "cgi-bin/x", 0, threading.Event()).result(timeout=5)
            time.sleep(0.1)
        self.dvr.handler = mock.Mock(side_effect=requests.exceptions.ReadTimeout("lento"))
        with self.assertLogs("camera_viewer.dvr", level="INFO") as logs:
            with self.assertRaises(requests.exceptions.ReadTimeout):
                light.submit_get("dvr", "u", "p", "cgi-bin/magicBox.cgi?action=getSystemInfo", 0, threading.Event()).result(timeout=5)
        self.assertEqual(logs.records[0].levelname, "WARNING")
        self.assertIn("consulta GET cgi-bin/magicBox.cgi?action=getSystemInfo", logs.output[0])
        self.assertIn("intentos=2", logs.output[0])

    def test_enable_is_idempotent_and_writes_to_the_given_stream(self) -> None:
        import io
        import logging

        from camera_viewer import dvr_log

        logger = logging.getLogger("camera_viewer.dvr")
        saved = list(logger.handlers), logger.level, logger.propagate
        logger.handlers.clear()
        self.addCleanup(lambda: (logger.handlers.clear(), logger.handlers.extend(saved[0]), setattr(logger, "level", saved[1]), setattr(logger, "propagate", saved[2])))
        stream = io.StringIO()
        dvr_log.enable(stream)
        dvr_log.enable(io.StringIO())
        self.assertEqual(len(logger.handlers), 1)
        logger.info("hola")
        self.assertIn("[dvr] hola", stream.getvalue())


class LanesAreIndependentTests(unittest.TestCase):
    def test_saturated_downloads_do_not_delay_light_queries(self) -> None:
        release = threading.Event()
        dvr = FakeDVR()

        def handler(url: str):
            if "loadfile" in url:
                release.wait(10)
                return FakeResponse(chunks=[b"x"])
            return FakeResponse(text="ok")

        dvr.handler = handler
        tmp = Path(tempfile.mkdtemp())
        with mock.patch.object(requests, "get", dvr):
            recordings = RecordingDownloadManager(max_concurrent=2, download_dir=tmp, post_download_gap=0)
            light = LightQueryManager(threads=2, retry_delay=0)
            downloads = [recordings.submit("dvr", "u", "p", ch, START, END, 0, threading.Event()) for ch in (1, 2, 3, 4)]
            time.sleep(0.3)
            started = time.monotonic()
            self.assertEqual(light.submit_get("dvr", "u", "p", "cgi-bin/x", 0, threading.Event()).result(timeout=5), "ok")
            self.assertLess(time.monotonic() - started, 1.0)
            self.assertEqual(sum("loadfile" in call for call in dvr.calls), 2)  # solo 2 descargas en curso
            release.set()
            for future in downloads:
                future.result(timeout=10)
            recordings.shutdown()
            light.shutdown()


class ServiceEndToEndTests(unittest.TestCase):
    """Cliente -> socket -> servicio real (en un hilo, puerto libre) -> DVR falso."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp())
        cls.recordings = RecordingDownloadManager(max_concurrent=2, download_dir=cls.tmp, post_download_gap=0)
        cls.light = LightQueryManager(threads=2, max_attempts=2, retry_delay=0)
        cls.patches = [mock.patch.object(download_service, "AUTHKEY_PATH", cls.tmp / "authkey")]
        cls.patches[0].start()
        # El puerto libre que se elige puede ser tomado por otro proceso antes de que el
        # servicio lo abra (las pruebas corren junto a otras): se reintenta con otro.
        for _attempt in range(8):
            with socket.socket() as sock:
                sock.bind(("localhost", 0))
                port = sock.getsockname()[1]
            address_patch = mock.patch.object(download_service, "SERVICE_ADDRESS", ("localhost", port))
            address_patch.start()
            threading.Thread(target=download_service.serve_forever, args=(cls.recordings, cls.light), daemon=True).start()
            deadline = time.monotonic() + 2
            while download_client._try_connect() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            conn = download_client._try_connect()
            if conn is not None:
                conn.close()
                cls.patches.append(address_patch)
                return
            address_patch.stop()
        raise RuntimeError("no se pudo levantar el servicio de prueba")

    @classmethod
    def tearDownClass(cls) -> None:
        for patch in cls.patches:
            patch.stop()

    def setUp(self) -> None:
        self.dvr = FakeDVR()
        patcher = mock.patch.object(requests, "get", self.dvr)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_find_files_through_service(self) -> None:
        def handler(url: str):
            if "factory.create" in url:
                return FakeResponse(text="result=5")
            if "findNextFile" in url:
                return FakeResponse(text=find_page("2026-09-18 12:00:00"))
            return FakeResponse(text="OK")

        self.dvr.handler = handler
        items = download_client.find_files("dvr", "u", "p", 2, START, END, 1, LightPriority.USER, threading.Event()).result(timeout=10)
        self.assertEqual(items[0]["StartTime"], "2026-09-18 12:00:00")

    def test_get_through_service(self) -> None:
        self.dvr.handler = lambda url: FakeResponse(text="sistema")
        future = download_client.get("dvr", "u", "p", "cgi-bin/magicBox.cgi?action=getSystemInfo", 0, threading.Event())
        self.assertEqual(future.result(timeout=10), "sistema")

    def test_query_failure_becomes_exception_on_client(self) -> None:
        self.dvr.handler = mock.Mock(side_effect=requests.exceptions.ConnectionError("caído"))
        future = download_client.get("dvr", "u", "p", "cgi-bin/x", 0, threading.Event())
        with self.assertRaises(RuntimeError) as ctx:
            future.result(timeout=10)
        self.assertIn("caído", str(ctx.exception))

    def test_download_through_service(self) -> None:
        self.dvr.handler = lambda url: FakeResponse(chunks=[b"video"])
        path = download_client.submit("dvr", "u", "p", 1, START, END, 0, threading.Event()).result(timeout=10)
        self.assertEqual(path.read_bytes(), b"video")
        path.unlink()

    def test_download_through_service_reports_progress_to_whoever_asks(self) -> None:
        gate = threading.Event()

        def chunks():
            yield b"aaaa"
            gate.wait(5)  # da tiempo a que el avance cruce el socket antes de terminar
            yield b"bb"

        class Slow(FakeResponse):
            def iter_content(self, chunk_size: int = 0):
                return chunks()

        self.dvr.handler = lambda url: Slow()
        seen: list[int] = []
        future = download_client.submit("dvr", "u", "p", 1, START, END, 0, threading.Event(), progress=seen.append)
        deadline = time.monotonic() + 5
        while 4 not in seen and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertIn(4, seen)
        gate.set()
        path = future.result(timeout=10)
        self.assertEqual(path.read_bytes(), b"aaaabb")
        self.assertEqual(seen, sorted(seen))  # el servicio manda el último valor: se saltan algunos, nunca retrocede
        path.unlink()

    def test_a_client_that_did_not_ask_for_progress_gets_only_the_final_answer(self) -> None:
        self.dvr.handler = lambda url: FakeResponse(chunks=[b"a", b"b", b"c"])
        path = download_client.submit("dvr", "u", "p", 1, START, END, 0, threading.Event()).result(timeout=10)
        self.assertEqual(path.read_bytes(), b"abc")
        path.unlink()

    def test_cancelling_a_query_frees_the_client(self) -> None:
        release = threading.Event()
        self.dvr.handler = lambda url: (release.wait(10), FakeResponse(text="tarde"))[1]
        stop = threading.Event()
        future = download_client.get("dvr", "u", "p", "cgi-bin/x", 0, stop)
        time.sleep(0.3)
        stop.set()
        with self.assertRaises(RuntimeError):
            future.result(timeout=5)
        release.set()


if __name__ == "__main__":
    unittest.main()
