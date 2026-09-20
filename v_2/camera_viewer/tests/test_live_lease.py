"""Concesión de vista en vivo: mientras dura, ninguna descarga arranca. Con un DVR falso.
Correr desde v_2/: .venv/bin/python -m unittest camera_viewer.tests.test_live_lease -v"""
from __future__ import annotations

import os
import socket
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import requests  # noqa: E402

from camera_viewer import download_client, download_service  # noqa: E402
from camera_viewer.download_manager import DownloadPriority, RecordingDownloadManager  # noqa: E402
from camera_viewer.tests.test_funnel import FakeDVR, FakeResponse  # noqa: E402

START = datetime(2026, 9, 18, 12, 0, 0)
END = datetime(2026, 9, 18, 12, 0, 45)


def make_dvr(delay: float = 0.0) -> FakeDVR:
    dvr = FakeDVR()
    dvr.delay = delay
    dvr.handler = lambda url: FakeResponse(chunks=[b"video"])
    return dvr


class ManagerLeaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.managers: list[RecordingDownloadManager] = []

    def manager(self, gap: float = 0.0) -> RecordingDownloadManager:
        manager = RecordingDownloadManager(max_concurrent=2, download_dir=self.tmp, post_download_gap=gap)
        self.managers.append(manager)
        self.addCleanup(manager.shutdown)
        return manager

    def submit(self, manager, priority: int = 0, channel: int = 1):
        return manager.submit("dvr", "u", "p", channel, START, END, priority, threading.Event())

    def patched(self, dvr: FakeDVR):
        patch = mock.patch.object(requests, "get", dvr)
        patch.start()
        self.addCleanup(patch.stop)

    def test_an_idle_manager_grants_the_lease_at_once_and_holds_new_jobs(self) -> None:
        self.patched(make_dvr())
        manager = self.manager()
        started = time.monotonic()
        self.assertTrue(manager.acquire_live(timeout=2))
        self.assertLess(time.monotonic() - started, 0.3)
        future = self.submit(manager)
        time.sleep(0.8)
        self.assertFalse(future.done())  # con la concesión, nada arranca
        self.assertEqual(manager.stats()["queued"], 1)
        manager.release_live()
        self.assertIsNotNone(future.result(timeout=5))

    def test_the_lease_waits_for_downloads_already_running(self) -> None:
        self.patched(make_dvr(delay=0.7))
        manager = self.manager()
        running = self.submit(manager)
        time.sleep(0.2)  # ya está descargando
        queued_during_wait: list = []

        def ask() -> None:
            self.granted_at = None
            if manager.acquire_live(timeout=5):
                self.granted_at = time.monotonic()

        thread = threading.Thread(target=ask)
        asked = time.monotonic()
        thread.start()
        time.sleep(0.1)
        queued_during_wait.append(self.submit(manager, channel=2))  # llega mientras se espera
        thread.join(5)
        self.assertIsNotNone(running.result(timeout=5))
        self.assertGreater(self.granted_at - asked, 0.5)  # esperó a que terminara la descarga
        self.assertFalse(queued_during_wait[0].done())  # y la que llegó después no arrancó
        manager.release_live()
        self.assertIsNotNone(queued_during_wait[0].result(timeout=5))

    def test_the_lease_also_waits_for_the_courtesy_gap(self) -> None:
        self.patched(make_dvr())
        manager = self.manager(gap=0.6)
        self.submit(manager).result(timeout=5)  # la descarga ya terminó, pero su pausa de cortesía sigue
        started = time.monotonic()
        self.assertTrue(manager.acquire_live(timeout=5))
        self.assertGreater(time.monotonic() - started, 0.3)
        manager.release_live()

    def test_timeout_returns_false_and_does_not_keep_the_lease(self) -> None:
        self.patched(make_dvr(delay=1.5))
        manager = self.manager()
        stuck = self.submit(manager)
        time.sleep(0.2)
        self.assertFalse(manager.acquire_live(timeout=0.3))
        self.assertEqual(manager.stats()["live_holders"], 0)
        later = self.submit(manager, channel=3)  # los trabajos siguen funcionando normal
        self.assertIsNotNone(stuck.result(timeout=5))
        self.assertIsNotNone(later.result(timeout=5))

    def test_two_holders_keep_downloads_paused_until_both_release(self) -> None:
        self.patched(make_dvr())
        manager = self.manager()
        self.assertTrue(manager.acquire_live(timeout=2))
        self.assertTrue(manager.acquire_live(timeout=2))
        future = self.submit(manager)
        manager.release_live()
        time.sleep(0.6)
        self.assertFalse(future.done())
        manager.release_live()
        self.assertIsNotNone(future.result(timeout=5))

    def test_queue_keeps_priority_order_while_paused(self) -> None:
        dvr = make_dvr()
        order: list[int] = []
        lock = threading.Lock()

        def handler(url: str):
            with lock:
                order.append(int(url.split("channel=")[1].split("&")[0]))
            return FakeResponse(chunks=[b"v"])

        dvr.handler = handler
        self.patched(dvr)
        manager = RecordingDownloadManager(max_concurrent=1, download_dir=self.tmp, post_download_gap=0)
        self.addCleanup(manager.shutdown)
        self.assertTrue(manager.acquire_live(timeout=2))
        futures = [
            self.submit(manager, DownloadPriority.BACKGROUND, channel=1),
            self.submit(manager, DownloadPriority.PREFETCH, channel=2),
            self.submit(manager, DownloadPriority.INTERACTIVE, channel=3),
        ]
        time.sleep(0.5)
        self.assertEqual(order, [])
        manager.release_live()
        for future in futures:
            future.result(timeout=5)
        self.assertEqual(order, [3, 2, 1])  # gana la prioridad, no el orden de llegada

    def test_stats(self) -> None:
        self.patched(make_dvr())
        manager = self.manager()
        self.assertEqual(manager.stats(), {"active": 0, "queued": 0, "live_holders": 0})


class ServiceLeaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp())
        cls.recordings = RecordingDownloadManager(max_concurrent=2, download_dir=cls.tmp, post_download_gap=0)
        patch = mock.patch.object(download_service, "AUTHKEY_PATH", cls.tmp / "authkey")
        patch.start()
        cls.patches = [patch]
        for _attempt in range(8):
            with socket.socket() as sock:
                sock.bind(("localhost", 0))
                port = sock.getsockname()[1]
            address_patch = mock.patch.object(download_service, "SERVICE_ADDRESS", ("localhost", port))
            address_patch.start()
            threading.Thread(target=download_service.serve_forever, args=(cls.recordings, None), daemon=True).start()
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
        patch = mock.patch.object(requests, "get", make_dvr())
        patch.start()
        self.addCleanup(patch.stop)

    def download(self):
        return download_client.submit("dvr", "u", "p", 1, START, END, 0, threading.Event())

    def test_downloads_wait_while_the_lease_is_held_and_resume_when_it_is_released(self) -> None:
        lease = download_client.acquire_live_lease(timeout=5)
        self.assertIsNotNone(lease)
        future = self.download()
        time.sleep(1.0)
        self.assertFalse(future.done())
        self.assertGreaterEqual(download_client.stats()["live_holders"], 1)
        lease.release()
        path = future.result(timeout=10)
        self.assertIsNotNone(path)
        path.unlink()
        self.assertEqual(download_client.stats()["live_holders"], 0)

    def test_the_lease_is_freed_if_the_holder_disappears_without_releasing(self) -> None:
        lease = download_client.acquire_live_lease(timeout=5)
        future = self.download()
        time.sleep(0.6)
        self.assertFalse(future.done())
        lease._conn.close()  # como si el proceso hubiera muerto: la conexión se corta sin aviso
        path = future.result(timeout=10)
        self.assertIsNotNone(path)
        path.unlink()

    def test_acquire_can_be_cancelled_while_waiting(self) -> None:
        slow = make_dvr(delay=3.0)
        with mock.patch.object(requests, "get", slow):
            running = self.download()
            time.sleep(0.4)
            stop = threading.Event()
            threading.Timer(0.5, stop.set).start()
            started = time.monotonic()
            self.assertIsNone(download_client.acquire_live_lease(stop, timeout=10))
            self.assertLess(time.monotonic() - started, 2.0)
            path = running.result(timeout=10)
        if path:
            path.unlink()
        time.sleep(0.5)
        self.assertEqual(download_client.stats()["live_holders"], 0)  # la concesión cancelada no quedó tomada


class DVRClientLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def make_client(self, lease_delay: float = 0.0):
        from camera_viewer import dvr_client

        client = dvr_client.DVRClient()
        self.opened: list[tuple[int, float]] = []
        self.released: list[float] = []
        self.lease_calls = 0
        started = time.monotonic()

        class FakeLease:
            def release(inner) -> None:
                self.released.append(time.monotonic() - started)

        def fake_acquire(stop_event=None, timeout=None):
            self.lease_calls += 1
            time.sleep(lease_delay)
            return FakeLease()

        def fake_worker(channel, host, stop_event, ready_event) -> None:
            self.opened.append((channel, time.monotonic() - started))
            stop_event.wait(10)

        patches = [
            mock.patch.object(dvr_client.download_client, "acquire_live_lease", fake_acquire),
            mock.patch.object(client, "_live_channel_worker", fake_worker),
            mock.patch.object(dvr_client, "LIVE_TO_RECORDINGS_SETTLE", 0.3),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.started = started
        return client

    def test_start_live_does_not_block_the_caller_and_opens_channels_only_after_the_lease(self) -> None:
        client = self.make_client(lease_delay=0.6)
        before = time.monotonic()
        client.start_live()
        self.assertLess(time.monotonic() - before, 0.2)  # la interfaz no se queda esperando al servicio
        time.sleep(0.3)
        self.assertEqual(self.opened, [])  # aún no hay concesión: ningún RTSP
        time.sleep(0.9)
        self.assertEqual(sorted(c for c, _ in self.opened), [1, 2, 3, 4])
        self.assertTrue(all(t >= 0.55 for _, t in self.opened))
        client.stop_live()

    def test_the_lease_is_released_after_the_settle_gap_when_live_stops(self) -> None:
        client = self.make_client()
        client.start_live()
        time.sleep(0.4)
        stopped = time.monotonic() - self.started
        client.stop_live()
        self.assertEqual(self.released, [])  # todavía no: los RTSP recién cerrados necesitan su margen
        time.sleep(0.6)
        self.assertEqual(len(self.released), 1)
        self.assertGreater(self.released[0] - stopped, 0.25)

    def test_stopping_before_the_lease_arrives_releases_it_and_opens_nothing(self) -> None:
        client = self.make_client(lease_delay=0.5)
        client.start_live()
        time.sleep(0.1)
        client.stop_live()
        time.sleep(0.8)
        self.assertEqual(self.opened, [])
        self.assertEqual(len(self.released), 1)  # la concesión tardía se devolvió, no quedó tomada


if __name__ == "__main__":
    unittest.main()
