"""Modelo de avance de una exportación y su ventana. Correr desde v_2/:
.venv/bin/python -m unittest camera_viewer.tests.test_export_progress -v"""
from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from camera_viewer import export_clip  # noqa: E402
from camera_viewer.export_clip import ClipRange, estimate_bytes  # noqa: E402
from camera_viewer.export_progress import (  # noqa: E402
    PHASE_CANCELLED,
    PHASE_DONE,
    PHASE_FAILED,
    ExportProgress,
)
from camera_viewer.save_progress_dialog import BACK, SaveProgressDialog, format_clock  # noqa: E402

START = datetime(2026, 9, 20, 8, 16, 20)
RANGE = ClipRange(START, START + timedelta(seconds=600))
MB = 1024 * 1024  # como format_size


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class ModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = Clock()
        self.model = ExportProgress(RANGE, Path("/tmp/x"), [1, 2, 3], clock=self.clock)
        self.expected = estimate_bytes(RANGE, 1)

    def test_a_queued_channel_has_no_progress_until_its_first_byte_report(self) -> None:
        item = self.model.channel(1)
        self.assertEqual(item.phase, export_clip.PHASE_QUEUED)
        self.assertEqual(self.model.fraction(1), 0.0)
        self.model.set_bytes(1, 0)
        self.assertEqual(item.phase, export_clip.PHASE_DOWNLOADING)

    def test_download_fraction_uses_the_estimate_and_never_reaches_100_by_itself(self) -> None:
        self.model.set_bytes(1, int(self.expected / 2))
        self.assertAlmostEqual(self.model.download_fraction(1), 0.5, places=2)
        self.assertAlmostEqual(self.model.fraction(1), 0.45, places=2)  # la descarga pesa 90 % del canal
        self.model.set_bytes(1, int(self.expected * 3))  # el estimado se quedó corto
        self.assertLess(self.model.download_fraction(1), 1.0)
        self.assertLess(self.model.fraction(1), 0.9)

    def test_later_phases_and_final_states_move_the_bar_forward(self) -> None:
        self.model.set_bytes(1, 10)
        self.model.set_phase(1, export_clip.PHASE_CONVERTING, "Convirtiendo…")
        self.assertGreater(self.model.fraction(1), 0.9)
        self.assertEqual(self.model.download_fraction(1), 1.0)
        self.model.set_phase(1, export_clip.PHASE_VERIFYING, "Verificando…")
        self.assertGreater(self.model.fraction(1), 0.95)
        self.model.mark_done(1, "/tmp/x/a.mp4", 123, None)
        self.assertEqual(self.model.fraction(1), 1.0)
        self.model.mark_failed(2, "No se pudo descargar del DVR", False)
        self.model.mark_failed(3, "Cancelado", True)
        self.assertEqual(self.model.channel(2).phase, PHASE_FAILED)
        self.assertEqual(self.model.channel(3).phase, PHASE_CANCELLED)
        self.assertEqual(self.model.overall_fraction(), 1.0)  # todos terminaron, bien o mal

    def test_a_finished_channel_ignores_late_events(self) -> None:
        self.model.mark_done(1, "/tmp/x/a.mp4", 123, None)
        self.model.set_bytes(1, 5)
        self.model.set_phase(1, export_clip.PHASE_QUEUED, "En cola…")
        self.assertEqual(self.model.channel(1).phase, PHASE_DONE)

    def test_overall_is_the_mean_of_the_channels(self) -> None:
        self.model.mark_done(1, "/tmp/x/a.mp4", 1, None)
        self.model.set_bytes(2, int(self.expected / 2))
        self.assertAlmostEqual(self.model.overall_fraction(), (1.0 + 0.45 + 0.0) / 3, places=2)

    def test_speed_and_eta_come_from_the_last_seconds(self) -> None:
        self.model.set_bytes(1, 0)
        for _ in range(6):
            self.clock.now += 1.0
            self.model.set_bytes(1, self.model.channel(1).bytes_done + 5 * MB)
        self.assertAlmostEqual(self.model.speed(1) / MB, 5.0, delta=0.5)
        remaining = self.expected - self.model.channel(1).bytes_done
        self.assertAlmostEqual(self.model.eta(1), remaining / self.model.speed(1), delta=1)

    def test_a_stalled_download_reads_zero_speed_and_no_eta(self) -> None:
        self.model.set_bytes(1, 0)
        self.clock.now += 1
        self.model.set_bytes(1, 5 * MB)
        self.clock.now += 10  # 10 s sin un solo byte más
        self.assertEqual(self.model.speed(1), 0.0)
        self.assertIsNone(self.model.eta(1))

    def test_no_speed_before_enough_samples_or_outside_the_download(self) -> None:
        self.assertIsNone(self.model.speed(1))
        self.model.set_bytes(1, 0)
        self.assertIsNone(self.model.speed(1))  # menos de 1 s de datos
        self.model.set_phase(1, export_clip.PHASE_CONVERTING, "Convirtiendo…")
        self.assertIsNone(self.model.speed(1))

    def test_a_retry_starts_counting_from_zero(self) -> None:
        self.model.set_bytes(1, 3 * MB)
        self.model.set_phase(1, export_clip.PHASE_RETRYING, "Reintentando la descarga…")
        self.assertEqual(self.model.channel(1).bytes_done, 0)
        self.model.set_bytes(1, 0)
        self.assertEqual(self.model.channel(1).phase, export_clip.PHASE_DOWNLOADING)

    def test_overall_eta_needs_some_progress_and_time_and_stops_when_finished(self) -> None:
        self.assertIsNone(self.model.overall_eta())
        self.model.set_bytes(1, int(self.expected / 2))
        self.clock.now += 10
        eta = self.model.overall_eta()
        self.assertIsNotNone(eta)
        self.assertGreater(eta, 0)
        self.model.finish()
        self.assertIsNone(self.model.overall_eta())

    def test_counts_and_cancel_flag(self) -> None:
        self.model.mark_done(1, "/tmp/x/a.mp4", 1, None)
        self.model.mark_failed(2, "Cancelado", True)
        self.assertEqual((self.model.saved_count(), self.model.total_count()), (1, 3))
        self.assertTrue(self.model.was_cancelled())
        self.assertFalse(self.model.cancelling)
        self.model.request_cancel()
        self.assertTrue(self.model.cancelling)


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.clock = Clock()
        self.model = ExportProgress(RANGE, Path("/tmp/x"), [1, 2], clock=self.clock)
        self.asked: list[str] = []
        self.answer = True
        self.window = SaveProgressDialog(self.model, confirm_cancel=self.ask)
        self.window.show()
        self.addCleanup(self.window.close)
        self.results: list[int] = []
        self.window.finished.connect(self.results.append)
        self.cancels: list[int] = []
        self.window.cancel_requested.connect(lambda: self.cancels.append(1))

    def ask(self, downloaded: str) -> bool:
        self.asked.append(downloaded)
        return self.answer

    def test_it_shows_one_card_per_channel_and_the_cancel_button_only(self) -> None:
        self.assertEqual(sorted(self.window.cards), [1, 2])
        self.assertTrue(self.window._cancel.isVisible())
        for button in (self.window._open_folder, self.window._back, self.window._close):
            self.assertFalse(button.isVisible())

    def test_the_cards_follow_the_model(self) -> None:
        self.assertEqual(self.window.cards[1]._phase.text(), "En cola")
        self.model.set_bytes(1, 0)
        self.clock.now += 2
        self.model.set_bytes(1, 30 * MB)
        self.model.changed.emit()
        card = self.window.cards[1]
        self.assertEqual(card._phase.text(), "Descargando del DVR")
        self.assertIn("30.0 MB de ≈", card._detail.text())
        self.assertIn("/s", card._detail.text())
        self.assertGreater(card._bar.value(), 0)
        self.assertEqual(self.window.cards[2]._phase.text(), "En cola")
        self.assertGreater(self.window._overall.value(), 0)

    def test_cancel_before_any_byte_does_not_ask(self) -> None:
        self.window._cancel.click()
        self.assertEqual(self.asked, [])
        self.assertEqual(self.cancels, [1])
        self.assertTrue(self.model.cancelling)
        self.assertFalse(self.window._cancel.isEnabled())
        self.assertEqual(self.window._cancel.text(), "Cancelando…")

    def test_cancel_with_data_downloaded_asks_first_and_can_be_declined(self) -> None:
        self.model.set_bytes(1, 12 * MB)
        self.answer = False
        self.window._cancel.click()
        self.assertEqual(self.asked, ["12.0 MB"])
        self.assertEqual(self.cancels, [])
        self.assertFalse(self.model.cancelling)
        self.answer = True
        self.window._cancel.click()
        self.assertEqual(self.cancels, [1])

    def test_escape_or_the_x_while_saving_is_a_cancel_request_not_a_close(self) -> None:
        self.model.set_bytes(1, 1 * MB)
        self.window.reject()
        self.assertEqual(self.asked, ["1.0 MB"])
        self.assertEqual(self.cancels, [1])
        self.assertTrue(self.window.isVisible())

    def test_success_shows_the_files_and_close_button(self) -> None:
        self.model.mark_done(1, "/tmp/x/CAM1_a.mp4", 5 * MB, None)
        self.model.mark_done(2, "/tmp/x/CAM2_a.mp4", 6 * MB, "dura 590 s de los 600 s pedidos")
        self.model.finish()
        self.model.changed.emit()
        self.assertIn("se guardó", self.window._headline.text())
        self.assertIn("CAM1_a.mp4", self.window.cards[1]._detail.text())
        self.assertIn("5.0 MB", self.window.cards[1]._detail.text())
        self.assertIn("Aviso: dura 590 s", self.window.cards[2]._detail.text())
        self.assertFalse(self.window._cancel.isVisible())
        self.assertTrue(self.window._open_folder.isVisible() and self.window._close.isVisible())
        self.assertFalse(self.window._back.isVisible())  # todo guardado: no hay nada que reintentar
        self.window._close.click()
        self.assertEqual(self.results, [SaveProgressDialog.DialogCode.Accepted])

    def test_partial_result_offers_going_back_to_the_clip(self) -> None:
        self.model.mark_done(1, "/tmp/x/CAM1_a.mp4", 5 * MB, None)
        self.model.mark_failed(2, "No se pudo descargar del DVR", False)
        self.model.finish()
        self.model.changed.emit()
        self.assertIn("1 de 2", self.window._headline.text())
        self.assertIn("1 de 2 canales guardados", self.window._overall.format())
        self.assertTrue(self.window._back.isVisible())
        self.window._back.click()
        self.assertEqual(self.results, [BACK])

    def test_total_failure_says_so_and_cannot_open_the_folder(self) -> None:
        self.model.mark_failed(1, "No se pudo descargar del DVR", False)
        self.model.mark_failed(2, "No se pudo descargar del DVR", False)
        self.model.finish()
        self.model.changed.emit()
        self.assertIn("No se pudo guardar", self.window._headline.text())
        self.assertFalse(self.window._open_folder.isVisible())
        self.assertTrue(self.window._back.isVisible())

    def test_cancelled_with_nothing_saved_goes_straight_back_to_the_clip(self) -> None:
        self.model.mark_failed(1, "Cancelado", True)
        self.model.mark_failed(2, "Cancelado", True)
        self.model.finish()
        self.model.changed.emit()
        self.app.processEvents()
        self.assertEqual(self.results, [BACK])
        self.assertFalse(self.window.isVisible())

    def test_cancelled_after_saving_some_keeps_them_and_lets_you_choose(self) -> None:
        self.model.mark_done(1, "/tmp/x/CAM1_a.mp4", 5 * MB, None)
        self.model.mark_failed(2, "Cancelado", True)
        self.model.finish()
        self.model.changed.emit()
        self.app.processEvents()
        self.assertTrue(self.window.isVisible())
        self.assertIn("Cancelado", self.window._headline.text())
        self.assertTrue(self.window._open_folder.isVisible() and self.window._back.isVisible())
        self.window.reject()  # la X al terminar equivale a "Cerrar"
        self.assertEqual(self.results, [SaveProgressDialog.DialogCode.Accepted])

    def test_clock_format(self) -> None:
        self.assertEqual(format_clock(5), "0:05")
        self.assertEqual(format_clock(65), "1:05")
        self.assertEqual(format_clock(3725), "1:02:05")


if __name__ == "__main__":
    unittest.main()
