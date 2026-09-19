"""Pausa / velocidad / cuadro a cuadro. Correr desde v_2/:
.venv/bin/python -m unittest camera_viewer.tests.test_playback_control -v"""
from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import Future
from pathlib import Path

import cv2
import numpy as np
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from camera_viewer.dvr_client import DVRClient
from camera_viewer.playback_control import PAUSED_STATUS, PlaybackControl
from camera_viewer.playback_controls import SPEEDS, PlaybackControls

CHANNELS = (1, 2, 3, 4)
FPS = 30
FRAMES = 60  # 2 s de video


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

    def test_speed_button_cycles_through_all_speeds_and_wraps(self) -> None:
        controls, seen = PlaybackControls(), []
        controls.set_active(True)
        controls.speed_selected.connect(lambda speed: (seen.append(speed), controls.set_speed(speed)))
        for _ in range(len(SPEEDS)):
            controls._speed_button.click()
        self.assertEqual(seen, [1.5, 2.0, 0.5, 1.0])

    def test_step_button_only_enabled_when_active_and_paused(self) -> None:
        controls = PlaybackControls()
        self.assertFalse(controls._step.isEnabled())
        controls.set_active(True)
        self.assertFalse(controls._step.isEnabled())
        controls.set_paused(True)
        self.assertTrue(controls._step.isEnabled())
        self.assertEqual(controls._pause.text(), "▶ Reanudar")
        controls.set_active(False)
        self.assertFalse(controls._step.isEnabled())


class PlayChunkTests(unittest.TestCase):
    """_play_chunk real, con un video sintético en disco (no toca el DVR)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.client = DVRClient()
        self.stop = threading.Event()
        self.semaphore = threading.Semaphore(2)
        self.frames = 0
        self.statuses: list[str] = []

        def on_frame(channel, frame) -> None:
            self.frames += 1
            self.semaphore.release()  # hace de "la interfaz ya lo mostró"

        # Directa: sin bucle de eventos en la prueba, una conexión en cola nunca se entrega.
        direct = Qt.ConnectionType.DirectConnection
        self.client.recording_frame_ready.connect(on_frame, direct)
        self.client.recording_channel_status.connect(lambda channel, text: self.statuses.append(text), direct)

    def make_clip(self) -> Future:
        path = Path(tempfile.mkdtemp()) / "clip.avi"
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (64, 48))
        for index in range(FRAMES):
            writer.write(np.full((48, 64, 3), index * 4 % 255, dtype=np.uint8))
        writer.release()
        future: Future = Future()
        future.set_result(path)
        return future

    def play(self, future: Future | None = None) -> tuple[threading.Thread, list[str]]:
        outcome: list[str] = []
        future = future or self.make_clip()
        thread = threading.Thread(
            target=lambda: outcome.append(
                self.client._play_chunk(0, 1, None, None, self.stop, self.semaphore, future)
            ),
            daemon=True,
        )
        thread.start()
        return thread, outcome

    def test_plays_at_real_time_and_double_speed(self) -> None:
        started = time.monotonic()
        thread, outcome = self.play()
        thread.join(10)
        normal = time.monotonic() - started
        self.assertEqual((outcome, self.frames), (["ended"], FRAMES))
        self.assertGreater(normal, 1.7)

        self.frames = 0
        self.client.control.set_speed(2.0)
        started = time.monotonic()
        thread, outcome = self.play()
        thread.join(10)
        fast = time.monotonic() - started
        self.assertEqual((outcome, self.frames), (["ended"], FRAMES))  # ningún cuadro se pierde a x2
        self.assertLess(fast, normal * 0.75)

    def test_pause_freezes_and_resume_continues_without_losing_or_repeating_frames(self) -> None:
        thread, outcome = self.play()
        time.sleep(0.5)
        self.client.toggle_pause()
        time.sleep(0.2)  # deja terminar el cuadro en vuelo
        frozen = self.frames
        time.sleep(0.6)
        self.assertEqual(self.frames, frozen)  # en pausa no avanza nada
        self.assertIn(PAUSED_STATUS, self.statuses)
        self.client.toggle_pause()
        thread.join(10)
        self.assertEqual((outcome, self.frames), (["ended"], FRAMES))

    def test_step_shows_one_frame_at_a_time_while_paused(self) -> None:
        self.client.control.reset(paused=True)
        thread, outcome = self.play()
        time.sleep(0.5)
        self.assertEqual(self.frames, 1)  # el primer cuadro se ve aunque arranque en pausa
        self.client.step_frame()
        time.sleep(0.3)
        self.assertEqual(self.frames, 2)
        time.sleep(0.4)
        self.assertEqual(self.frames, 2)
        self.stop.set()
        thread.join(5)
        self.assertEqual(outcome, ["stopped"])

    def test_cancel_while_paused_returns_promptly(self) -> None:
        thread, outcome = self.play()
        time.sleep(0.3)
        self.client.toggle_pause()
        time.sleep(0.2)
        started = time.monotonic()
        self.stop.set()
        thread.join(5)
        self.assertEqual(outcome, ["stopped"])
        self.assertLess(time.monotonic() - started, 1.0)


if __name__ == "__main__":
    unittest.main()
