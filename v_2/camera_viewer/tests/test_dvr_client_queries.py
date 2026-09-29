"""search() y find_recorded_days() (camera_viewer/dvr_client.py): consultan los 4 canales por
separado -- 2026-09-28, antes un solo canal atascado dejaba SIN NADA lo que los otros 3 sí habían
traído (el timeline entero vacío, o el calendario sin ningún día marcado). Con dobles: nunca habla
con el DVR de verdad. Correr desde v_2/:
.venv/bin/python -m unittest camera_viewer.tests.test_dvr_client_queries -v"""
from __future__ import annotations

import os
import unittest
from concurrent.futures import Future
from datetime import datetime
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from camera_viewer import dvr_client  # noqa: E402
from camera_viewer.clip import Clip  # noqa: E402


def done_future(result=None, exc: Exception | None = None) -> Future:
    future: Future = Future()
    if exc is not None:
        future.set_exception(exc)
    else:
        future.set_result(result)
    return future


class DvrClientQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def make_client(self, per_channel: dict[int, Future]):
        client = dvr_client.DVRClient()
        patch = mock.patch.object(
            client, "_submit_find", lambda channel, *a, **k: per_channel[channel]
        )
        patch.start()
        self.addCleanup(patch.stop)
        self.clips_ready: list[list[Clip]] = []
        self.search_failed: list[str] = []
        self.recorded_days_ready: list[tuple[int, int, set]] = []
        self.recorded_days_failed: list[str] = []
        client.clips_ready.connect(lambda clips: self.clips_ready.append(clips))
        client.search_failed.connect(lambda msg: self.search_failed.append(msg))
        client.recorded_days_ready.connect(lambda y, m, days: self.recorded_days_ready.append((y, m, days)))
        client.recorded_days_failed.connect(lambda msg: self.recorded_days_failed.append(msg))
        return client

    def run_worker(self, client, worker, *args) -> None:
        # Sin el hilo propio de search()/find_recorded_days(): corre el worker directo y
        # entrega a mano las señales en cola (vienen de "otro hilo" para Qt aunque aquí no lo
        # sea de verdad, por el QThread afín de las señales).
        worker(*args)
        self.app.processEvents()

    def test_one_channel_failing_does_not_wipe_out_the_clips_from_the_others(self) -> None:
        ok_item = [{"StartTime": "2026-09-28 10:00:00", "EndTime": "2026-09-28 10:05:00"}]
        client = self.make_client({
            1: done_future(ok_item),
            2: done_future(exc=RuntimeError("caído")),
            3: done_future(ok_item),
            4: done_future(ok_item),
        })
        self.run_worker(client, client._search_worker, datetime(2026, 9, 28), datetime(2026, 9, 28, 23, 59, 59), 0)
        self.assertEqual(len(self.clips_ready), 1)
        self.assertEqual(len(self.clips_ready[0]), 3)  # los 3 canales que sí respondieron
        self.assertEqual(len(self.search_failed), 1)
        self.assertIn("2", self.search_failed[0])  # nombra el canal que falló

    def test_all_channels_failing_still_emits_an_empty_ready_signal(self) -> None:
        client = self.make_client({c: done_future(exc=RuntimeError("caído")) for c in (1, 2, 3, 4)})
        self.run_worker(client, client._search_worker, datetime(2026, 9, 28), datetime(2026, 9, 28, 23, 59, 59), 0)
        self.assertEqual(self.clips_ready, [[]])
        self.assertEqual(len(self.search_failed), 1)

    def test_no_failures_means_no_failed_signal_at_all(self) -> None:
        ok_item = [{"StartTime": "2026-09-28 10:00:00", "EndTime": "2026-09-28 10:05:00"}]
        client = self.make_client({c: done_future(ok_item) for c in (1, 2, 3, 4)})
        self.run_worker(client, client._search_worker, datetime(2026, 9, 28), datetime(2026, 9, 28, 23, 59, 59), 0)
        self.assertEqual(len(self.clips_ready[0]), 4)
        self.assertEqual(self.search_failed, [])

    def test_recorded_days_survives_one_failing_channel(self) -> None:
        ok_item = [{"StartTime": "2026-09-15 10:00:00", "EndTime": "2026-09-15 10:05:00"}]
        client = self.make_client({
            1: done_future(ok_item),
            2: done_future(exc=RuntimeError("caído")),
            3: done_future([]),
            4: done_future([]),
        })
        self.run_worker(client, client._find_recorded_days_worker, 2026, 9)
        self.assertEqual(len(self.recorded_days_ready), 1)
        year, month, days = self.recorded_days_ready[0]
        self.assertEqual(days, {datetime(2026, 9, 15).date()})
        self.assertEqual(len(self.recorded_days_failed), 1)
        self.assertIn("2", self.recorded_days_failed[0])


if __name__ == "__main__":
    unittest.main()
