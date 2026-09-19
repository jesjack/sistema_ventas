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

    def test_reverse_flag_changes_status_text_and_epoch(self) -> None:
        self.assertFalse(self.control.reverse)
        before = self.control.epoch
        self.control.set_reverse(True)
        self.assertTrue(self.control.reverse)
        self.assertGreater(self.control.epoch, before)
        self.assertEqual(self.control.status_text(), "Reversa x1")
        self.control.set_speed(2.0)
        self.assertEqual(self.control.status_text(), "Reversa x2")
        self.control.set_paused(True)
        self.assertEqual(self.control.status_text(), PAUSED_STATUS)
        again = self.control.epoch
        self.control.set_reverse(True)  # sin cambio: no toca el reloj
        self.assertEqual(self.control.epoch, again)

    def test_seek_request_reaches_every_channel_and_last_one_wins(self) -> None:
        from datetime import datetime

        first, second = datetime(2026, 9, 19, 10, 0, 5), datetime(2026, 9, 19, 10, 0, 40)
        self.control.request_seek(first)
        self.control.request_seek(second)
        self.assertEqual(self.control.peek_seek(2), second)
        self.assertEqual([self.control.take_seek(c) for c in CHANNELS], [second] * 4)
        self.assertIsNone(self.control.take_seek(1))

    def test_paused_seek_grants_one_frame_per_channel(self) -> None:
        from datetime import datetime

        self.control.set_paused(True)
        self.control.request_seek(datetime(2026, 9, 19, 10, 0, 5))
        self.assertEqual(self.control.wait_turn(1, self.never), "step")

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
        controls._faster.click()
        controls._faster.click()
        self.assertFalse(controls._faster.isEnabled())  # ya en la velocidad máxima
        controls._slower.click()
        controls._slower.click()
        controls._slower.click()
        self.assertFalse(controls._slower.isEnabled())  # ya en la mínima
        self.assertEqual(seen, [1.5, 2.0, 1.5, 1.0, 0.5])
        self.assertEqual(controls._speed_button.text(), "x0.5")

    def test_speed_label_is_a_button_that_restores_x1(self) -> None:
        controls, seen = PlaybackControls(), []
        controls.speed_selected.connect(lambda speed: (seen.append(speed), controls.set_speed(speed)))
        controls.set_active(True)
        self.assertFalse(controls._speed_button.isEnabled())  # en x1 no hay nada que restaurar
        controls.set_speed(2.0)
        self.assertTrue(controls._speed_button.isEnabled())
        controls._speed_button.click()
        self.assertEqual((seen, controls._speed_button.text()), ([1.0], "x1"))
        self.assertFalse(controls._speed_button.isEnabled())

    def test_direction_button_toggles_between_normal_and_reverse(self) -> None:
        controls, seen = PlaybackControls(), []
        controls.reverse_toggled.connect(seen.append)
        controls.set_active(True)
        self.assertEqual(controls._direction.text(), "Normal")
        controls._direction.click()
        self.assertEqual((seen, controls._direction.isChecked()), ([True], True))
        controls.set_reverse(True)
        self.assertEqual(controls._direction.text(), "Reversa")
        controls._direction.click()
        self.assertEqual(seen, [True, False])

    def test_there_is_no_frame_step_button(self) -> None:
        controls = PlaybackControls()
        self.assertFalse(hasattr(controls, "_step"))
        self.assertFalse(hasattr(controls, "step_clicked"))

    def test_all_controls_have_the_same_height(self) -> None:
        controls = PlaybackControls()
        controls.show()
        self.assertEqual({widget.height() for widget in controls._buttons}, {30})

    def test_controls_are_disabled_until_a_playback_is_active(self) -> None:
        controls = PlaybackControls()
        self.assertTrue(all(not button.isEnabled() for button in controls._buttons))
        controls.set_active(True)
        self.assertTrue(controls._pause.isEnabled() and controls._direction.isEnabled())


if __name__ == "__main__":
    unittest.main()
