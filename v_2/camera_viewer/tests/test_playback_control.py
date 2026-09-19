"""Pausa / velocidad / cuadro a cuadro. Correr desde v_2/:
.venv/bin/python -m unittest camera_viewer.tests.test_playback_control -v"""
from __future__ import annotations

import os
import threading
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from camera_viewer.playback_control import PAUSED_STATUS, PlaybackControl
from camera_viewer.playback_controls import SPEEDS, PlaybackControls

CHANNELS = (1, 2, 3, 4)


class PlaybackControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.control = PlaybackControl(CHANNELS)
        self.never = lambda: False

    def test_default_state_lets_frames_go(self) -> None:
        self.assertEqual(self.control.wait_turn(1, self.never), "go")
        self.assertEqual(self.control.status_text(), "x1")

    def test_speed_status_text(self) -> None:
        self.control.set_speed(0.5)
        self.assertEqual(self.control.status_text(), "x0.5")
        self.control.set_speed(2.0)
        self.assertEqual(self.control.status_text(), "x2")

    def test_paused_blocks_until_resumed(self) -> None:
        self.control.set_paused(True)
        self.assertEqual(self.control.status_text(), PAUSED_STATUS)
        result: list[str] = []
        thread = threading.Thread(target=lambda: result.append(self.control.wait_turn(1, self.never)))
        thread.start()
        time.sleep(0.3)
        self.assertTrue(thread.is_alive())
        self.control.set_paused(False)
        thread.join(2)
        self.assertEqual(result, ["go"])

    def test_wait_turn_returns_stop_when_cancelled_while_paused(self) -> None:
        self.control.set_paused(True)
        stop = threading.Event()
        result: list[str] = []
        thread = threading.Thread(target=lambda: result.append(self.control.wait_turn(1, stop.is_set)))
        thread.start()
        time.sleep(0.2)
        stop.set()
        thread.join(2)
        self.assertEqual(result, ["stop"])

    def test_step_lets_exactly_one_frame_per_channel(self) -> None:
        self.assertFalse(self.control.step())  # sin pausa no hace nada
        self.control.set_paused(True)
        self.assertTrue(self.control.step())
        self.assertEqual(self.control.wait_turn(2, self.never), "step")
        result: list[str] = []
        thread = threading.Thread(target=lambda: result.append(self.control.wait_turn(2, self.never)))
        thread.start()
        time.sleep(0.3)
        self.assertTrue(thread.is_alive())  # el segundo cuadro espera otro paso
        self.control.set_paused(False)
        thread.join(2)

    def test_reset_paused_grants_one_frame_and_keeps_speed(self) -> None:
        self.control.set_speed(0.5)
        self.control.reset(paused=True)
        self.assertEqual(self.control.speed, 0.5)
        self.assertEqual(self.control.wait_turn(3, self.never), "step")

    def test_epoch_changes_on_resume_and_speed_only(self) -> None:
        start = self.control.epoch
        self.control.set_paused(True)
        self.assertEqual(self.control.epoch, start)
        self.control.set_paused(False)
        self.assertGreater(self.control.epoch, start)
        before = self.control.epoch
        self.control.set_speed(0.5)
        self.assertGreater(self.control.epoch, before)

    def test_playing_channels_tracking(self) -> None:
        self.control.mark_playing(1, True)
        self.control.mark_playing(2, True)
        self.control.mark_playing(1, False)
        self.assertEqual(self.control.playing_channels(), {2})


class PlaybackControlsWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_speed_buttons_step_through_the_speeds_and_stop_at_the_ends(self) -> None:
        controls, seen = PlaybackControls(), []
        controls.speed_selected.connect(lambda speed: (seen.append(speed), controls.set_speed(speed)))
        controls.set_active(True)
        self.assertFalse(controls._slower.isEnabled() and controls._speed == SPEEDS[0])
        controls._faster.click()
        controls._faster.click()
        self.assertFalse(controls._faster.isEnabled())  # ya en la velocidad máxima
        controls._slower.click()
        controls._slower.click()
        controls._slower.click()
        self.assertFalse(controls._slower.isEnabled())  # ya en la mínima
        self.assertEqual(seen, [1.5, 2.0, 1.5, 1.0, 0.5])
        self.assertEqual(controls._speed_label.text(), "x0.5")

    def test_all_controls_have_the_same_height(self) -> None:
        controls = PlaybackControls()
        controls.show()
        heights = {widget.height() for widget in (*controls._buttons, controls._speed_label)}
        self.assertEqual(len(heights), 1, heights)

    def test_step_button_only_enabled_when_active_and_paused(self) -> None:
        controls = PlaybackControls()
        self.assertFalse(controls._step.isEnabled())
        controls.set_active(True)
        self.assertFalse(controls._step.isEnabled())
        controls.set_paused(True)
        self.assertTrue(controls._step.isEnabled())
        self.assertEqual(controls._pause.text(), "Reanudar")
        controls.set_active(False)
        self.assertFalse(controls._step.isEnabled())


if __name__ == "__main__":
    unittest.main()
