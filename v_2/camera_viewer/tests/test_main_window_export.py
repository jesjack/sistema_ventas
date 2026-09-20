"""Enganche de la ventana principal con la ventana de guardado (sin red). Correr desde v_2/:
.venv/bin/python -m unittest camera_viewer.tests.test_main_window_export -v"""
from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from camera_viewer import main_window  # noqa: E402
from camera_viewer.clip import Clip  # noqa: E402
from camera_viewer.dvr_client import DVRClient  # noqa: E402
from camera_viewer.export_bar import IDLE  # noqa: E402
from camera_viewer.export_clip import ClipRange  # noqa: E402

DAY = datetime(2026, 9, 19)


def at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return DAY.replace(hour=hour, minute=minute, second=second)


class FakeDialog:
    instances: list["FakeDialog"] = []
    returns: ClipRange | None = None

    def __init__(self, client, clips, clip_range, settings=None, parent=None) -> None:
        self.client, self.clips, self.range = client, clips, clip_range
        self.paused_while_open: bool | None = None
        FakeDialog.instances.append(self)

    def exec(self) -> int:
        self.paused_while_open = window_holder[0].client.control.paused
        return 0

    def final_range(self) -> ClipRange | None:
        return FakeDialog.returns


window_holder: list = []


class MainWindowClipDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        FakeDialog.instances = []
        FakeDialog.returns = None
        patches = [
            mock.patch.object(DVRClient, "search"),
            mock.patch.object(DVRClient, "find_recorded_days"),
            mock.patch.object(main_window, "ClipExportDialog", FakeDialog),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.w = main_window.MainWindow()
        window_holder[:] = [self.w]
        self.addCleanup(self.w.client.stop_playback)  # (no close(): su closeEvent termina el proceso con os._exit)
        self.w._clips_by_channel = {c: [Clip(c, at(9), at(11))] for c in (1, 2, 3, 4)}
        control = self.w.client.control
        control.reset(False, at(10, 5, 30))
        for channel in (1, 2, 3, 4):
            control.announce_ready(channel)

    def test_marks_then_save_opens_the_window_with_the_range_and_a_client_of_its_own(self) -> None:
        clip_range = ClipRange(at(10, 5, 30), at(10, 6, 10))
        self.w.export_flow.marks = [clip_range.start, clip_range.end]
        self.w.export_flow.save_clip()
        dialog = FakeDialog.instances[0]
        self.assertEqual(dialog.range, clip_range)
        self.assertIsNot(dialog.client, self.w.client)  # reproducción aparte
        self.assertEqual((dialog.client.host, dialog.client.username), (self.w.client.host, self.w.client.username))
        self.assertEqual(set(dialog.clips), {1, 2, 3, 4})

    def test_the_main_playback_is_paused_while_the_window_is_open_and_restored_after(self) -> None:
        self.w.export_flow.marks = [at(10, 5, 30), at(10, 6, 10)]
        self.assertFalse(self.w.client.control.paused)
        self.w.export_flow.save_clip()
        self.assertTrue(FakeDialog.instances[0].paused_while_open)
        self.assertFalse(self.w.client.control.paused)  # como estaba
        self.assertEqual(self.w.playback_controls._pause.text(), "Pausa")

    def test_if_it_was_already_paused_it_stays_paused(self) -> None:
        self.w.client.control.set_paused(True)
        self.w.playback_controls.set_paused(True)
        self.w.export_flow.marks = [at(10, 5, 30), at(10, 6, 10)]
        self.w.export_flow.save_clip()
        self.assertTrue(self.w.client.control.paused)

    def test_the_range_adjusted_in_the_window_updates_the_marks_and_the_band(self) -> None:
        FakeDialog.returns = ClipRange(at(10, 5, 10), at(10, 6, 40))
        self.w.export_flow.marks = [at(10, 5, 30), at(10, 6, 10)]
        self.w.export_flow.save_clip()
        self.assertEqual(self.w.export_flow.marks, [at(10, 5, 10), at(10, 6, 40)])
        self.assertEqual(self.w.timeline._export_range, (at(10, 5, 10), at(10, 6, 40)))

    def test_the_main_bar_stays_minimal_and_the_window_is_reused(self) -> None:
        self.w.export_flow.marks = [at(10, 5, 30), at(10, 6, 10)]
        self.w.export_flow.save_clip()
        self.w.export_flow.save_clip()
        self.assertEqual(self.w.export_bar.state, IDLE)
        self.assertEqual(len(FakeDialog.instances), 2)
        self.assertIs(FakeDialog.instances[0].client, FakeDialog.instances[1].client)  # un solo cliente para toda la sesión


    def test_closing_the_app_during_an_export_cancels_it_and_waits_for_its_cleanup(self) -> None:
        import threading

        cleaned = threading.Event()
        cancelled = threading.Event()

        def worker() -> None:
            cancelled.wait(5)
            cleaned.set()  # el hilo real borra aquí sus .part

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        fake = mock.Mock()
        fake.finished.return_value = False
        fake.thread = thread
        fake.cancel.side_effect = cancelled.set
        self.w.export_flow.export = fake
        with mock.patch.object(main_window.os, "_exit") as exit_:
            self.w.close()
        fake.cancel.assert_called_once()
        self.assertTrue(cleaned.is_set())  # se esperó a que terminara antes de matar el proceso
        exit_.assert_called_once_with(0)

if __name__ == "__main__":
    unittest.main()
