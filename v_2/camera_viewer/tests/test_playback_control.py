"""Pausa / velocidad / cuadro a cuadro. Correr desde v_2/:
.venv/bin/python -m unittest camera_viewer.tests.test_playback_control -v"""
from __future__ import annotations

import os
import threading
import time
import unittest
from datetime import datetime, timedelta
from unittest import mock

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
        self.assertEqual(self.control.wait_turn(1, self.never), "seek")  # el salto se atiende primero
        self.control.take_seek(1)
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


T0 = datetime(2026, 9, 19, 10, 0, 0)


class ClockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.control = PlaybackControl(CHANNELS)
        self.never = lambda: False

    def start_clock(self, target: datetime = T0) -> None:
        self.control.reset(False, target)
        for channel in CHANNELS:
            self.control.announce_ready(channel)

    def test_no_clock_until_a_playback_is_armed(self) -> None:
        self.assertFalse(self.control.has_clock())
        self.assertIsNone(self.control.media_now())

    def test_the_clock_waits_for_every_channel_before_starting(self) -> None:
        self.control.reset(False, T0)
        self.assertTrue(self.control.has_clock() and not self.control.clock_running())
        for channel in (1, 2, 3):
            self.control.announce_ready(channel)
        self.assertFalse(self.control.clock_running())
        self.control.announce_ready(4)
        self.assertTrue(self.control.clock_running())

    def test_wait_turn_holds_channels_until_the_barrier_opens(self) -> None:
        self.control.reset(False, T0)
        results: list[str] = []
        threads = [threading.Thread(target=lambda c=c: results.append(self.control.wait_turn(c, self.never))) for c in (1, 2)]
        for thread in threads:
            thread.start()
        time.sleep(0.3)
        self.assertEqual(results, [])  # nadie arranca solo
        for channel in CHANNELS:
            self.control.announce_ready(channel)
        for thread in threads:
            thread.join(2)
        self.assertEqual(results, ["go", "go"])

    def test_absent_channels_do_not_hold_the_others_back(self) -> None:
        self.control.reset(False, T0)
        for channel in (1, 2, 3):
            self.control.announce_ready(channel)
        self.control.announce_absent(4)
        self.assertTrue(self.control.clock_running())

    def test_the_clock_starts_after_the_timeout_without_the_slow_channel(self) -> None:
        with mock.patch("camera_viewer.playback_control.BARRIER_TIMEOUT", 0.2):
            self.control.reset(False, T0)
            self.control.announce_ready(1)
            self.assertEqual(self.control.wait_turn(1, self.never), "go")  # esperó el tope y arrancó
            self.assertTrue(self.control.clock_running())

    def test_media_time_advances_with_speed_and_freezes_on_pause(self) -> None:
        self.start_clock()
        time.sleep(0.3)
        self.assertAlmostEqual((self.control.media_now() - T0).total_seconds(), 0.3, delta=0.08)
        self.control.set_speed(2.0)
        before = self.control.media_now()
        time.sleep(0.3)
        self.assertAlmostEqual((self.control.media_now() - before).total_seconds(), 0.6, delta=0.12)
        self.control.set_paused(True)
        frozen = self.control.media_now()
        time.sleep(0.3)
        self.assertEqual(self.control.media_now(), frozen)
        self.control.set_paused(False)
        time.sleep(0.2)
        self.assertGreater(self.control.media_now(), frozen)

    def test_changing_speed_or_direction_does_not_make_the_clock_jump(self) -> None:
        self.start_clock()
        time.sleep(0.3)
        before = self.control.media_now()
        self.control.set_speed(2.0)
        self.control.set_reverse(True)
        after = self.control.media_now()
        self.assertLess(abs((after - before).total_seconds()), 0.05)
        time.sleep(0.3)
        self.assertLess(self.control.media_now(), after)  # ahora retrocede

    def test_wall_for_maps_video_time_to_real_time(self) -> None:
        self.start_clock()
        now = time.monotonic()
        self.assertAlmostEqual(self.control.wall_for(T0 + timedelta(seconds=1)) - now, 1.0, delta=0.05)
        self.control.set_speed(2.0)
        self.assertAlmostEqual(self.control.wall_for(self.control.media_now() + timedelta(seconds=1)) - time.monotonic(), 0.5, delta=0.05)
        self.control.set_reverse(True)
        self.assertAlmostEqual(self.control.wall_for(self.control.media_now() - timedelta(seconds=1)) - time.monotonic(), 0.5, delta=0.05)

    def test_a_seek_rearms_the_barrier_at_the_new_time(self) -> None:
        self.start_clock()
        target = T0 + timedelta(seconds=90)
        self.control.request_seek(target)
        self.assertFalse(self.control.clock_running())
        self.assertEqual(self.control.media_now(), target)

    def test_paused_playback_never_starts_the_clock_until_resumed(self) -> None:
        self.control.reset(True, T0)
        for channel in CHANNELS:
            self.control.announce_ready(channel)
        self.assertFalse(self.control.clock_running())
        self.control.set_paused(False)
        self.assertTrue(self.control.clock_running())
        self.assertAlmostEqual((self.control.media_now() - T0).total_seconds(), 0.0, delta=0.05)


class BoundsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.control = PlaybackControl(CHANNELS)
        self.start, self.end = T0 + timedelta(seconds=10), T0 + timedelta(seconds=40)

    def start_clock(self, target: datetime) -> None:
        self.control.set_bounds(self.start, self.end)
        self.control.reset(False, target)
        for channel in CHANNELS:
            self.control.announce_ready(channel)

    def test_no_bounds_by_default_and_nothing_is_out_of_range(self) -> None:
        self.assertIsNone(self.control.bounds())
        self.assertFalse(self.control.out_of_bounds(T0 + timedelta(days=1)))

    def test_out_of_bounds_depends_on_the_direction(self) -> None:
        self.control.set_bounds(self.start, self.end)
        self.assertFalse(self.control.out_of_bounds(self.end - timedelta(milliseconds=33)))
        self.assertTrue(self.control.out_of_bounds(self.end))  # el fin es exclusivo
        self.assertFalse(self.control.out_of_bounds(self.start - timedelta(seconds=5)))  # antes del inicio, en avance, no molesta
        self.control.set_reverse(True)
        self.assertTrue(self.control.out_of_bounds(self.start - timedelta(milliseconds=33)))
        self.assertFalse(self.control.out_of_bounds(self.start))

    def test_seek_and_start_are_clamped_into_the_range(self) -> None:
        self.control.set_bounds(self.start, self.end)
        self.control.reset(False, T0)  # antes del inicio
        self.assertEqual(self.control.media_now(), self.start)
        self.control.request_seek(T0 + timedelta(seconds=500))
        self.assertLess(self.control.media_now(), self.end)
        self.assertGreater(self.control.media_now(), self.end - timedelta(seconds=1))

    def test_the_clock_never_leaves_the_range(self) -> None:
        self.control.set_speed(2.0)
        self.start_clock(self.end - timedelta(seconds=0.2))
        time.sleep(0.6)  # a x2 se pasaría del fin
        self.assertEqual(self.control.media_now(), self.end)

    def test_reach_bound_pauses_everything_at_the_end_once(self) -> None:
        self.start_clock(self.start)
        self.control.reach_bound()
        self.assertTrue(self.control.paused)
        self.assertEqual(self.control.bound_reached(), "end")
        self.assertEqual(self.control.media_now(), self.end)
        self.control.reach_bound()  # varios canales lo llaman: idempotente
        self.assertEqual(self.control.bound_reached(), "end")

    def test_reverse_stops_at_the_start(self) -> None:
        self.control.set_reverse(True)
        self.start_clock(self.start + timedelta(seconds=1))
        self.control.reach_bound()
        self.assertEqual((self.control.bound_reached(), self.control.media_now()), ("start", self.start))

    def test_resuming_or_seeking_clears_the_bound_flag(self) -> None:
        self.start_clock(self.start)
        self.control.reach_bound()
        self.control.set_paused(False)
        self.assertIsNone(self.control.bound_reached())
        self.control.reach_bound()
        self.control.request_seek(self.start)
        self.assertIsNone(self.control.bound_reached())

    def test_clear_bounds(self) -> None:
        self.control.set_bounds(self.start, self.end)
        self.control.clear_bounds()
        self.assertIsNone(self.control.bounds())
        self.assertFalse(self.control.out_of_bounds(self.end + timedelta(days=1)))


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
