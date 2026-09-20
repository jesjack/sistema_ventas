"""Ventana de guardado de un clip, con un cliente de reproducción falso. Correr desde v_2/:
.venv/bin/python -m unittest camera_viewer.tests.test_clip_export_dialog -v"""
from __future__ import annotations

import os
import queue
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from camera_viewer.clip import Clip  # noqa: E402
from camera_viewer.clip_export_dialog import ClipExportDialog  # noqa: E402
from camera_viewer.export_bar import EXPORTING, FINISHED, PREVIEW  # noqa: E402
from camera_viewer.export_clip import ClipRange  # noqa: E402
from camera_viewer.playback_control import PlaybackControl  # noqa: E402

CHANNELS = (1, 2, 3, 4)
DAY = datetime(2026, 9, 19)
NOW = DAY.replace(hour=12)


def at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return DAY.replace(hour=hour, minute=minute, second=second)


class FakeClient(QObject):
    recording_frame_ready = Signal(int, object)
    recording_channel_status = Signal(int, str)
    host, username, password = "dvr", "u", "p"

    def __init__(self) -> None:
        super().__init__()
        self.control = PlaybackControl(CHANNELS)
        self.playback_active = False
        self.calls: list[tuple] = []
        self.consumed: list[int] = []

    def play_from(self, start: datetime, clips, start_delay: float = 0.0, paused: bool = False) -> None:
        self.calls.append(("play_from", start))
        self.control.reset(paused, start)
        for channel in CHANNELS:
            self.control.announce_ready(channel)
        self.playback_active = True

    def seek(self, target: datetime, resume: bool = False) -> None:
        self.calls.append(("seek", target, resume))
        if resume and self.control.paused:
            self.control.set_paused(False)
        self.control.request_seek(target)

    def set_reverse(self, reverse: bool) -> None:
        self.control.set_reverse(reverse)

    def set_speed(self, speed: float) -> None:
        self.control.set_speed(speed)

    def toggle_pause(self) -> bool:
        return self.control.toggle_pause()

    def stop_playback(self) -> None:
        self.calls.append(("stop",))
        self.playback_active = False

    def notify_recording_frame_consumed(self, channel: int) -> None:
        self.consumed.append(channel)


class FakeExport:
    def __init__(self) -> None:
        self.events: queue.Queue = queue.Queue()
        self.cancelled = False
        self._finished = False

    def cancel(self) -> None:
        self.cancelled = True

    def finished(self) -> bool:
        return self._finished

    def push(self, *event) -> None:
        self.events.put(event)
        if event[0] == "finished":
            self._finished = True


class DialogTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.client = FakeClient()
        self.export = FakeExport()
        self.started: list[tuple] = []
        self.clips = {c: [Clip(c, at(9), at(11, 30))] for c in CHANNELS}
        self.folder = Path(tempfile.mkdtemp()) / "clips"

    def open(self, clip_range: ClipRange | None = None, clips=None) -> ClipExportDialog:
        def starter(host, user, password, channels, rng, folder):
            self.started.append((list(channels), rng, Path(folder)))
            return self.export

        dialog = ClipExportDialog(
            self.client, clips or self.clips, clip_range or ClipRange(at(10, 5, 30), at(10, 6, 10)),
            settings=None, now=lambda: NOW, starter=starter,
        )
        dialog.flow._folder = self.folder
        dialog.show()
        self.app.processEvents()  # corre el arranque diferido (QTimer.singleShot(0))
        self.addCleanup(lambda: dialog.close())
        return dialog


class OpeningTests(DialogTestCase):
    def test_shows_the_four_channels_and_starts_its_own_playback_at_the_start_of_the_clip(self) -> None:
        dialog = self.open()
        self.assertEqual(sorted(dialog.grid.panels), [1, 2, 3, 4])
        self.assertEqual(self.client.calls[0], ("play_from", at(10, 5, 30)))
        self.assertEqual(self.client.control.bounds(), (at(10, 5, 30), at(10, 6, 10)))
        self.assertEqual(dialog.bar.state, PREVIEW)
        self.assertTrue(dialog.controls._pause.isEnabled())

    def test_it_starts_forward_at_normal_speed_even_if_the_client_was_left_reversed(self) -> None:
        self.client.control.set_reverse(True)
        self.client.control.set_speed(2.0)
        dialog = self.open()
        self.assertFalse(self.client.control.reverse)
        self.assertEqual(self.client.control.speed, 1.0)
        self.assertEqual(dialog.controls._speed_button.text(), "x1")

    def test_own_timeline_shows_the_segment_with_context_and_the_recorded_coverage(self) -> None:
        dialog = self.open()
        self.assertEqual(dialog.timeline.export_range(), (at(10, 5, 30), at(10, 6, 10)))
        self.assertEqual(dialog.timeline.context(), (at(10, 5, 20), at(10, 6, 20)))  # 40 s -> margen de 10 s
        self.assertEqual(dialog.timeline._coverage, [(at(9), at(11, 30))])

    def test_the_context_margin_scales_with_the_clip_and_is_capped(self) -> None:
        for seconds, pad in ((30, 10), (240, 60), (3600, 120)):
            dialog = self.open(ClipRange(at(10, 0), at(10, 0) + timedelta(seconds=seconds)))
            start, end = dialog.timeline.context()
            self.assertEqual(((at(10, 0) - start).total_seconds(), (end - (at(10, 0) + timedelta(seconds=seconds))).total_seconds()), (pad, pad), seconds)
            dialog.close()

    def test_the_context_never_goes_past_what_is_recorded_or_the_present(self) -> None:
        self.clips = {c: [Clip(c, at(10, 5, 25), at(11, 59, 55))] for c in CHANNELS}
        dialog = self.open(ClipRange(at(10, 5, 30), at(10, 6, 10)))
        self.assertEqual(dialog.timeline.context()[0], at(10, 5, 25))  # el margen de atrás se recorta a la primera grabación
        near_now = self.open(ClipRange(at(11, 59, 30), at(11, 59, 50)))
        self.assertLessEqual(near_now.timeline.context()[1], NOW)


class PlaybackTests(DialogTestCase):
    def test_frames_go_to_the_right_panel_and_are_acknowledged_so_playback_keeps_flowing(self) -> None:
        dialog = self.open()
        frame = np.full((48, 64, 3), 120, dtype=np.uint8)
        self.client.recording_frame_ready.emit(2, frame)
        self.app.processEvents()
        self.assertIsNotNone(dialog.grid.panels[2]._pixmap_item)
        self.assertIsNone(dialog.grid.panels[1]._pixmap_item)
        self.assertEqual(self.client.consumed, [2])

    def test_channel_statuses_are_shown_on_the_panels(self) -> None:
        dialog = self.open()
        self.client.recording_channel_status.emit(3, "Descargando 10:05:30...")
        self.app.processEvents()
        self.assertEqual(dialog.grid.panels[3]._status_label.text(), "Descargando 10:05:30...")

    def test_jump_buttons_move_the_clock_and_stay_inside_the_clip(self) -> None:
        dialog = self.open()
        self.client.control.reset(True, at(10, 5, 35))
        self.client.control.set_bounds(at(10, 5, 30), at(10, 6, 10))
        dialog._jump(-10)
        self.assertEqual(self.client.control.media_now(), at(10, 5, 30))  # no se sale por detrás
        dialog._jump(500)
        self.assertLess(self.client.control.media_now(), at(10, 6, 10))  # ni por delante

    def test_pause_reverse_and_speed_are_its_own(self) -> None:
        dialog = self.open()
        dialog.controls._pause.click()
        self.assertTrue(self.client.control.paused)
        self.assertEqual(dialog.controls._pause.text(), "Reanudar")
        dialog.controls._direction.click()
        self.assertTrue(self.client.control.reverse)
        dialog.controls._faster.click()
        self.assertEqual(self.client.control.speed, 1.5)

    def test_clicking_the_timeline_seeks(self) -> None:
        dialog = self.open()
        dialog.timeline.seek_requested.emit(at(10, 5, 50))
        self.assertEqual(self.client.calls[-1][:2], ("seek", at(10, 5, 50)))

    def test_resuming_at_the_end_of_the_clip_starts_it_over(self) -> None:
        dialog = self.open()
        self.client.control.reach_bound()
        dialog._tick()
        self.assertEqual(dialog.controls._pause.text(), "Reanudar")  # se pausó sola y el botón lo refleja
        dialog._toggle_pause()
        self.assertEqual(self.client.calls[-1], ("seek", at(10, 5, 30), True))
        self.assertFalse(self.client.control.paused)


class RangeAdjustmentTests(DialogTestCase):
    def test_dragging_a_handle_changes_the_bounds_the_band_and_the_size_estimate(self) -> None:
        dialog = self.open()
        before = dialog.bar._size_label.text()
        dialog.timeline.range_changed.emit(at(10, 5, 20), at(10, 6, 10))  # alargar 10 s hacia atrás
        self.assertEqual(self.client.control.bounds(), (at(10, 5, 20), at(10, 6, 10)))
        self.assertEqual(dialog.timeline.export_range(), (at(10, 5, 20), at(10, 6, 10)))
        self.assertIn("50 s", dialog.bar._range_label.text())
        self.assertNotEqual(dialog.bar._size_label.text(), before)

    def test_a_range_beyond_the_context_is_clamped(self) -> None:
        dialog = self.open()
        dialog.timeline.range_changed.emit(at(9, 0), at(12, 0))
        start, end = self.client.control.bounds()
        self.assertEqual((start, end), dialog.timeline.context())

    def test_the_mark_buttons_adjust_from_the_current_position(self) -> None:
        dialog = self.open()
        self.client.control.reset(True, at(10, 5, 50))
        self.client.control.set_bounds(at(10, 5, 30), at(10, 6, 10))
        dialog.bar._mark_start.click()
        self.assertEqual(self.client.control.bounds(), (at(10, 5, 50), at(10, 6, 10)))

    def test_less_than_one_second_is_refused_and_the_band_snaps_back(self) -> None:
        dialog = self.open()
        dialog.timeline.range_changed.emit(at(10, 6, 9, ), at(10, 6, 9) + timedelta(milliseconds=300))
        self.assertEqual(self.client.control.bounds(), (at(10, 5, 30), at(10, 6, 10)))
        self.assertEqual(dialog.timeline.export_range(), (at(10, 5, 30), at(10, 6, 10)))


class SavingAndClosingTests(DialogTestCase):
    def test_cancel_closes_stops_its_playback_and_disconnects_from_the_client(self) -> None:
        dialog = self.open()
        dialog.bar._cancel_preview.click()
        self.assertFalse(dialog.isVisible())
        self.assertIn(("stop",), self.client.calls)
        self.assertIsNone(self.client.control.bounds())
        self.client.recording_frame_ready.emit(1, np.zeros((4, 4, 3), dtype=np.uint8))
        self.app.processEvents()
        self.assertEqual(self.client.consumed, [])  # ya no escucha al cliente

    def test_the_adjusted_range_is_what_the_main_window_gets_back(self) -> None:
        dialog = self.open()
        dialog.timeline.range_changed.emit(at(10, 5, 40), at(10, 6, 5))
        dialog.reject()
        self.assertEqual(dialog.final_range(), ClipRange(at(10, 5, 40), at(10, 6, 5)))

    def test_saving_uses_the_chosen_channels_range_and_folder_and_shows_progress_then_the_result(self) -> None:
        dialog = self.open()
        dialog.bar._checks[4].setChecked(False)
        dialog.bar._confirm.click()
        self.assertEqual(self.started, [([1, 2, 3], ClipRange(at(10, 5, 30), at(10, 6, 10)), self.folder)])
        self.assertEqual(dialog.bar.state, EXPORTING)
        for channel in (1, 2, 3):
            self.export.push("done", channel, f"c{channel}.mp4", None)
        self.export.push("finished", {})
        dialog.flow._poll()
        self.assertEqual(dialog.bar.state, FINISHED)
        self.assertTrue(dialog.isVisible())  # la ventana sigue abierta mostrando el resultado
        dialog.bar._dismiss.click()
        self.assertFalse(dialog.isVisible())

    def test_closing_while_saving_cancels_the_export(self) -> None:
        dialog = self.open()
        dialog.bar._confirm.click()
        dialog.close()
        self.assertTrue(self.export.cancelled)

    def test_the_folder_button_asks_for_a_folder_through_the_dialog(self) -> None:
        dialog = self.open()
        chosen = Path(tempfile.mkdtemp())
        with mock.patch("camera_viewer.clip_export_dialog.QFileDialog.getExistingDirectory", return_value=str(chosen)):
            dialog.bar._folder_button.click()
        self.assertIn(str(chosen), dialog.bar._folder_button.text())


if __name__ == "__main__":
    unittest.main()
