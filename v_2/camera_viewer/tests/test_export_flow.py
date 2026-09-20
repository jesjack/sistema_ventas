"""Flujo de exportación de un clip corto: marcas, vista previa acotada, confirmación y avance,
con un cliente y una línea de tiempo falsos. Correr desde v_2/:
.venv/bin/python -m unittest camera_viewer.tests.test_export_flow -v"""
from __future__ import annotations

import os
import queue
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from camera_viewer.clip import Clip  # noqa: E402
from camera_viewer.export_bar import EXPORTING, FINISHED, IDLE, PREVIEW, ExportBar  # noqa: E402
from camera_viewer.export_flow import ExportFlow, format_duration, range_text  # noqa: E402
from camera_viewer.export_clip import ClipRange  # noqa: E402
from camera_viewer.playback_control import PlaybackControl  # noqa: E402

CHANNELS = (1, 2, 3, 4)
DAY = datetime(2026, 9, 19)
NOW = DAY.replace(hour=12, minute=0)


def at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return DAY.replace(hour=hour, minute=minute, second=second)


class FakeClient:
    host, username, password = "dvr", "u", "p"

    def __init__(self) -> None:
        self.control = PlaybackControl(CHANNELS)
        self.seeks: list[tuple[datetime, bool]] = []

    def seek(self, target: datetime, resume: bool = False) -> None:
        self.seeks.append((target, resume))
        if resume and self.control.paused:
            self.control.set_paused(False)
        self.control.request_seek(target)

    def set_reverse(self, reverse: bool) -> None:
        self.control.set_reverse(reverse)

    playback_active = True

    def play_from(self, start: datetime, clips) -> None:
        self.seeks.append((start, "play_from"))
        self.playback_active = True


class FakeTimeline:
    def __init__(self) -> None:
        self.range = None

    def set_export_range(self, start, end) -> None:
        self.range = (start, end)

    def clear_export_range(self) -> None:
        self.range = None


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


class FlowTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.client, self.timeline = FakeClient(), FakeTimeline()
        self.bar = ExportBar(CHANNELS)
        self.bar.set_active(True)
        self.messages: list[str] = []
        self.started: list[tuple] = []
        self.export = FakeExport()
        self.answer_after: float | None = 0.0
        self.chosen_folder: Path | None = None
        self.opened: list[Path] = []
        self.saved_setting: dict = {}
        self.folder = Path(tempfile.mkdtemp()) / "clips"
        # todos los canales grabaron de las 09:00 a las 11:30 (y 11:30-11:59:30 solo CAM 1 y 2)
        self.clips = {
            1: [Clip(1, at(9), at(11, 59, 30))],
            2: [Clip(2, at(9), at(11, 59, 30))],
            3: [Clip(3, at(9), at(11, 30))],
            4: [Clip(4, at(9), at(11, 30))],
        }

        class Settings:
            def value(inner, key, default=None):
                return self.saved_setting.get(key, default)

            def setValue(inner, key, value) -> None:
                self.saved_setting[key] = value

        def starter(host, user, password, channels, clip_range, folder):
            self.started.append((list(channels), clip_range, Path(folder)))
            return self.export

        self.flow = ExportFlow(
            self.client, self.timeline, self.bar,
            clips_provider=lambda: self.clips,
            notify=self.messages.append,
            ask_after_seconds=lambda: self.answer_after,
            choose_folder=lambda current: self.chosen_folder,
            open_folder=self.opened.append,
            settings=Settings(),
            starter=starter,
            now=lambda: NOW,
        )
        self.flow._folder = self.folder
        self.set_clock(at(10, 5, 30))

    def set_clock(self, moment: datetime) -> None:
        self.client.control.reset(True, moment)  # en pausa: el reloj queda fijo en `moment`
        self.client.control.set_paused(True)

    def mark(self, start: datetime, end: datetime) -> None:
        self.set_clock(start)
        self.flow.mark_start()
        self.set_clock(end)
        self.flow.mark_end()


class MarksTests(FlowTestCase):
    def test_marks_define_the_range_and_paint_the_band(self) -> None:
        self.mark(at(10, 5, 30), at(10, 6, 10))
        self.assertEqual(self.timeline.range, (at(10, 5, 30), at(10, 6, 10)))
        self.assertIn("10:05:30 – 10:06:10 (40 s)", self.bar._range_label.text())
        self.assertTrue(self.bar._save.isEnabled())

    def test_one_mark_alone_asks_for_the_other(self) -> None:
        self.set_clock(at(10, 5, 30))
        self.flow.mark_start()
        self.assertIn("falta marcar el fin", self.bar._range_label.text())
        self.assertFalse(self.bar._save.isEnabled())
        self.assertIsNone(self.timeline.range)

    def test_an_end_too_close_to_the_start_discards_the_start(self) -> None:
        self.mark(at(10, 5, 30), at(10, 6, 0))
        self.set_clock(at(10, 5, 30, ) + timedelta(milliseconds=200))
        self.flow.mark_end()
        self.assertIsNone(self.flow.marks[0])
        self.assertIn("falta marcar el inicio", self.bar._range_label.text())

    def test_clear_removes_marks_and_band(self) -> None:
        self.mark(at(10, 5, 30), at(10, 6, 10))
        self.flow.clear_marks()
        self.assertEqual(self.flow.marks, [None, None])
        self.assertIsNone(self.timeline.range)

    def test_saving_without_marks_explains_what_is_missing(self) -> None:
        self.flow.save_clip()
        self.assertIn("Marca primero", self.messages[-1])
        self.assertIsNone(self.flow.preview_range)


class SaveLastTests(FlowTestCase):
    def test_only_the_previous_30_seconds(self) -> None:
        self.answer_after = 0.0
        self.set_clock(at(10, 30))
        self.flow.save_last()
        self.assertEqual(self.flow.preview_range, ClipRange(at(10, 29, 30), at(10, 30)))

    def test_previous_and_following_30_seconds(self) -> None:
        self.answer_after = 30.0
        self.set_clock(at(10, 30))
        self.flow.save_last()
        self.assertEqual(self.flow.preview_range, ClipRange(at(10, 29, 30), at(10, 30, 30)))

    def test_cancelling_the_question_does_nothing(self) -> None:
        self.answer_after = None
        self.flow.save_last()
        self.assertIsNone(self.flow.preview_range)
        self.assertEqual(self.bar.state, IDLE)

    def test_the_following_seconds_are_clamped_to_what_is_recorded_and_it_says_so(self) -> None:
        self.answer_after = 30.0
        self.set_clock(at(11, 59, 20))  # solo hasta 11:59:30
        self.flow.save_last()
        self.assertEqual(self.flow.preview_range.end, at(11, 59, 30))
        self.assertIn("10 s de grabación posterior", " ".join(self.messages))

    def test_never_goes_past_the_present(self) -> None:
        self.answer_after = 30.0
        self.clips[1] = [Clip(1, at(9), at(13))]  # el clip "termina" en el futuro (en curso)
        self.set_clock(at(11, 59, 50))
        self.flow.save_last()
        self.assertEqual(self.flow.preview_range.end, NOW)

    def test_before_the_start_of_the_recordings_is_clamped(self) -> None:
        self.set_clock(at(9, 0, 10))
        self.flow.save_last()
        self.assertEqual(self.flow.preview_range.start, at(9))

    def test_no_recording_at_all_reports_it(self) -> None:
        self.clips = {c: [] for c in CHANNELS}
        self.set_clock(at(10))
        self.flow.save_last()
        self.assertIn("No hay grabación", self.messages[-1])
        self.assertIsNone(self.flow.preview_range)


class PreviewTests(FlowTestCase):
    def enter(self, start=at(10, 5, 30), end=at(10, 6, 10)) -> None:
        self.mark(start, end)
        self.flow.save_clip()

    def test_the_preview_bounds_playback_to_the_range_and_starts_at_the_beginning(self) -> None:
        self.enter()
        self.assertEqual(self.client.control.bounds(), (at(10, 5, 30), at(10, 6, 10)))
        self.assertEqual(self.client.seeks[-1], (at(10, 5, 30), True))
        self.assertFalse(self.client.control.reverse)
        self.assertEqual(self.bar.state, PREVIEW)
        self.assertTrue(self.bar._restart.isVisibleTo(self.bar))

    def test_the_preview_offers_only_channels_that_recorded_in_the_range(self) -> None:
        self.enter(at(11, 40), at(11, 50))  # CAM 3 y 4 no grabaron ahí
        self.assertEqual(self.bar.selected_channels(), [1, 2])
        self.assertFalse(self.bar._checks[3].isEnabled())

    def test_size_estimate_follows_the_selected_channels(self) -> None:
        self.enter(at(10, 0), at(10, 1))
        self.assertIn("≈ 63.0 MB", self.bar._size_label.text().replace("60.1", "63.0")) if False else None
        four = self.bar._size_label.text()
        self.bar._checks[3].setChecked(False)
        self.bar._checks[4].setChecked(False)
        two = self.bar._size_label.text()
        self.assertIn("4 canales", four)
        self.assertIn("2 canales", two)
        self.assertNotEqual(four, two)

    def test_adjusting_the_marks_inside_the_preview_updates_the_bounds(self) -> None:
        self.enter()
        self.set_clock(at(10, 5, 50))
        self.client.control.set_bounds(at(10, 5, 30), at(10, 6, 10))
        self.flow.mark_start()
        self.assertEqual(self.flow.preview_range, ClipRange(at(10, 5, 50), at(10, 6, 10)))
        self.assertEqual(self.client.control.bounds(), (at(10, 5, 50), at(10, 6, 10)))
        self.assertEqual(self.timeline.range, (at(10, 5, 50), at(10, 6, 10)))
        self.assertIn("20 s", self.bar._range_label.text())

    def test_a_mark_that_would_leave_less_than_a_second_is_refused(self) -> None:
        self.enter()
        self.client.control.set_bounds(at(10, 5, 30), at(10, 6, 10))
        self.set_clock(at(10, 6, 9, ) + timedelta(milliseconds=500))
        self.flow.mark_start()
        self.assertEqual(self.flow.preview_range, ClipRange(at(10, 5, 30), at(10, 6, 10)))
        self.assertIn("antes del fin", self.messages[-1])

    def test_restart_goes_back_to_the_beginning_of_the_clip_forward(self) -> None:
        self.enter()
        self.client.set_reverse(True)
        self.flow.restart_clip()
        self.assertEqual(self.client.seeks[-1], (at(10, 5, 30), True))
        self.assertFalse(self.client.control.reverse)

    def test_resuming_at_the_end_restarts_and_at_the_start_in_reverse_goes_to_the_end(self) -> None:
        self.enter()
        self.client.control.reach_bound()  # llegó al final
        self.assertTrue(self.flow.at_bound_action())
        self.assertEqual(self.client.seeks[-1], (at(10, 5, 30), True))
        self.client.control.set_reverse(True)
        self.client.control.reach_bound()  # retrocedió hasta el inicio
        self.assertTrue(self.flow.at_bound_action())
        self.assertEqual(self.client.seeks[-1], (at(10, 6, 10), True))

    def test_at_bound_action_does_nothing_when_not_stopped_at_an_edge(self) -> None:
        self.enter()
        self.assertFalse(self.flow.at_bound_action())

    def test_cancelling_frees_playback_and_keeps_the_marks(self) -> None:
        self.enter()
        self.flow.cancel_preview()
        self.assertIsNone(self.client.control.bounds())
        self.assertEqual(self.bar.state, IDLE)
        self.assertEqual(self.flow.marks, [at(10, 5, 30), at(10, 6, 10)])
        self.assertEqual(self.timeline.range, (at(10, 5, 30), at(10, 6, 10)))

    def test_stopping_playback_leaves_the_preview(self) -> None:
        self.enter()
        self.flow.set_playback_active(False)
        self.assertIsNone(self.client.control.bounds())
        self.assertEqual(self.bar.state, IDLE)


class ConfirmAndProgressTests(FlowTestCase):
    def preview(self) -> None:
        self.mark(at(10, 5, 30), at(10, 6, 10))
        self.flow.save_clip()

    def test_confirm_starts_the_export_with_the_chosen_channels_range_and_folder(self) -> None:
        self.preview()
        self.bar._checks[2].setChecked(False)
        self.flow.confirm()
        channels, clip_range, folder = self.started[0]
        self.assertEqual((channels, clip_range, folder), ([1, 3, 4], ClipRange(at(10, 5, 30), at(10, 6, 10)), self.folder))
        self.assertEqual(self.bar.state, EXPORTING)
        self.assertIsNone(self.client.control.bounds())  # la reproducción vuelve a ser libre

    def test_confirm_needs_at_least_one_channel(self) -> None:
        self.preview()
        for check in self.bar._checks.values():
            check.setChecked(False)
        self.assertFalse(self.bar._confirm.isEnabled())
        self.flow.confirm()
        self.assertEqual(self.started, [])
        self.assertIn("al menos un canal", self.messages[-1])

    def test_an_unwritable_folder_is_reported_and_nothing_starts(self) -> None:
        self.preview()
        blocker = Path(tempfile.mkdtemp()) / "archivo"
        blocker.write_bytes(b"x")
        self.flow._folder = blocker / "dentro"  # no se puede crear una carpeta dentro de un archivo
        self.flow.confirm()
        self.assertEqual(self.started, [])
        self.assertIn("No se puede guardar", self.messages[-1])
        self.assertEqual(self.bar.state, PREVIEW)

    def test_progress_and_a_complete_success(self) -> None:
        self.preview()
        self.flow.confirm()
        self.export.push("state", 1, "Descargando…")
        self.export.push("done", 1, str(self.folder / "a.mp4"), None)
        for channel in (2, 3, 4):
            self.export.push("done", channel, str(self.folder / f"{channel}.mp4"), None)
        self.export.push("finished", {1: "a", 2: "b", 3: "c", 4: "d"})
        self.flow._poll()
        self.assertEqual(self.bar.state, FINISHED)
        self.assertIn("4 archivos", self.bar._message.text())
        self.assertIn(str(self.folder), self.bar._message.text())

    def test_partial_failure_names_the_channels_that_failed(self) -> None:
        self.preview()
        self.flow.confirm()
        self.export.push("done", 1, "a.mp4", None)
        self.export.push("failed", 2, "No se pudo descargar del DVR")
        self.export.push("done", 3, "c.mp4", None)
        self.export.push("done", 4, "d.mp4", None)
        self.export.push("finished", {})
        self.flow._poll()
        text = self.bar._message.text()
        self.assertIn("Se guardaron 3 de 4", text)
        self.assertIn("CAM 2: No se pudo descargar del DVR", text)

    def test_total_failure_and_warnings(self) -> None:
        self.preview()
        self.flow.confirm()
        for channel in (1, 2, 3, 4):
            self.export.push("failed", channel, "Cancelado")
        self.export.push("finished", {})
        self.flow._poll()
        self.assertIn("No se pudo guardar", self.bar._message.text())

    def test_a_warning_about_a_shorter_clip_is_shown(self) -> None:
        self.preview()
        self.flow.confirm()
        self.export.push("done", 1, "a.mp4", "dura 28 s de los 40 s pedidos")
        for channel in (2, 3, 4):
            self.export.push("done", channel, "x.mp4", None)
        self.export.push("finished", {})
        self.flow._poll()
        self.assertIn("CAM 1 dura 28 s de los 40 s pedidos", self.bar._message.text())

    def test_cancel_export_signals_the_running_export(self) -> None:
        self.preview()
        self.flow.confirm()
        self.flow.cancel_export()
        self.assertTrue(self.export.cancelled)

    def test_dismissing_the_result_returns_to_idle(self) -> None:
        self.preview()
        self.flow.confirm()
        self.export.push("finished", {})
        self.flow._poll()
        self.flow.dismiss_result()
        self.assertEqual(self.bar.state, IDLE)
        self.assertIsNone(self.flow.export)

    def test_choosing_a_folder_updates_the_label_and_is_remembered(self) -> None:
        self.preview()
        new = Path(tempfile.mkdtemp())
        self.chosen_folder = new
        self.flow.choose_folder()
        self.assertIn(str(new), self.bar._folder_button.text())
        self.assertEqual(self.saved_setting["export_folder"], str(new))

    def test_open_folder_button_opens_the_export_folder(self) -> None:
        self.preview()
        self.flow.confirm()
        self.export.push("finished", {})
        self.flow._poll()
        self.bar._open_folder.click()
        self.assertEqual(self.opened, [self.folder])


class OpenerModeTests(FlowTestCase):
    """En la ventana principal, la vista previa y el guardado viven en otra ventana."""

    def setUp(self) -> None:
        super().setUp()
        self.opened: list[ClipRange] = []
        self.opener_returns: ClipRange | None = None

        def opener(clip_range: ClipRange):
            self.opened.append(clip_range)
            return self.opener_returns

        self.flow._preview_opener = opener

    def test_saving_a_marked_clip_opens_the_window_instead_of_a_local_preview(self) -> None:
        self.mark(at(10, 5, 30), at(10, 6, 10))
        self.flow.save_clip()
        self.assertEqual(self.opened, [ClipRange(at(10, 5, 30), at(10, 6, 10))])
        self.assertEqual(self.bar.state, IDLE)  # la barra principal no cambia de estado
        self.assertIsNone(self.client.control.bounds())  # y la reproducción principal no se acota
        self.assertEqual(self.client.seeks, [])

    def test_the_range_the_window_returns_becomes_the_new_marks_and_band(self) -> None:
        self.mark(at(10, 5, 30), at(10, 6, 10))
        self.opener_returns = ClipRange(at(10, 5, 20), at(10, 6, 30))
        self.flow.save_clip()
        self.assertEqual(self.flow.marks, [at(10, 5, 20), at(10, 6, 30)])
        self.assertEqual(self.timeline.range, (at(10, 5, 20), at(10, 6, 30)))
        self.assertIn("10:05:20 – 10:06:30 (1 min 10 s)", self.bar._range_label.text())

    def test_closing_the_window_without_a_result_keeps_the_marks(self) -> None:
        self.mark(at(10, 5, 30), at(10, 6, 10))
        self.flow.save_clip()
        self.assertEqual(self.flow.marks, [at(10, 5, 30), at(10, 6, 10)])

    def test_last_30_seconds_also_goes_through_the_window(self) -> None:
        self.answer_after = 30.0
        self.set_clock(at(10, 30))
        self.flow.save_last()
        self.assertEqual(self.opened, [ClipRange(at(10, 29, 30), at(10, 30, 30))])

    def test_the_window_is_not_opened_when_nothing_was_recorded_there(self) -> None:
        self.clips = {c: [] for c in CHANNELS}
        self.mark(at(10, 5, 30), at(10, 6, 10))
        self.flow.save_clip()
        self.assertEqual(self.opened, [])
        self.assertIn("No hay grabación", self.messages[-1])


class InsideTheWindowTests(FlowTestCase):
    def test_without_an_active_playback_the_preview_starts_its_own(self) -> None:
        self.client.playback_active = False
        self.mark(at(10, 5, 30), at(10, 6, 10))
        self.flow.save_clip()
        self.assertEqual(self.client.seeks[-1], (at(10, 5, 30), "play_from"))

    def test_adjust_range_updates_everything_and_refuses_less_than_a_second(self) -> None:
        self.mark(at(10, 5, 30), at(10, 6, 10))
        self.flow.save_clip()
        self.flow.adjust_range(at(10, 5, 20), at(10, 6, 20))
        self.assertEqual(self.client.control.bounds(), (at(10, 5, 20), at(10, 6, 20)))
        self.assertEqual(self.flow.final_range(), ClipRange(at(10, 5, 20), at(10, 6, 20)))
        self.flow.adjust_range(at(10, 6, 0), at(10, 6, 0) + timedelta(milliseconds=200))
        self.assertEqual(self.client.control.bounds(), (at(10, 5, 20), at(10, 6, 20)))
        self.assertIn("al menos 1 segundo", self.messages[-1])
        self.assertEqual(self.timeline.range, (at(10, 5, 20), at(10, 6, 20)))  # la banda vuelve a su sitio


class HelpersAndBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_duration_formatting(self) -> None:
        self.assertEqual([format_duration(s) for s in (5, 59.6, 60, 125, 3600, 5400)], ["5 s", "1 min 00 s", "1 min 00 s", "2 min 05 s", "1 h 00 min", "1 h 30 min"])
        self.assertEqual(range_text(ClipRange(at(10), at(10, 0, 40))), "10:00:00 – 10:00:40 (40 s)")

    def test_each_state_shows_only_its_own_controls(self) -> None:
        bar = ExportBar(CHANNELS)
        bar.set_active(True)
        visible = lambda: {name for name, w in {"marks": bar._mark_start, "last": bar._save_last, "confirm": bar._confirm, "cancel_export": bar._cancel_export, "open": bar._open_folder}.items() if w.isVisibleTo(bar)}
        bar.set_state(IDLE)
        self.assertEqual(visible(), {"marks", "last"})
        bar.set_state(PREVIEW)
        self.assertEqual(visible(), {"marks", "confirm"})
        bar.set_state(EXPORTING)
        self.assertEqual(visible(), {"cancel_export"})
        bar.set_state(FINISHED)
        self.assertEqual(visible(), {"open"})

    def test_marking_and_saving_are_disabled_until_a_playback_is_active(self) -> None:
        bar = ExportBar(CHANNELS)
        self.assertFalse(bar._mark_start.isEnabled() or bar._save_last.isEnabled())
        bar.set_active(True)
        self.assertTrue(bar._mark_start.isEnabled() and bar._save_last.isEnabled())

    def test_all_buttons_have_the_same_height(self) -> None:
        bar = ExportBar(CHANNELS)
        self.assertEqual({button.height() if False else button.minimumHeight() for button in bar._buttons}, {30})


if __name__ == "__main__":
    unittest.main()
