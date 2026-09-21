"""Exportar horas: modelo de avance, botón-barra, ventana de selección, panel y controlador (sin red ni
ffmpeg). Correr desde v_2/: .venv/bin/python -m unittest camera_viewer.tests.test_hours_ui -v"""
from __future__ import annotations

import os
import queue
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from camera_viewer import progress_button  # noqa: E402
from camera_viewer.clip import Clip  # noqa: E402
from camera_viewer.export_hours import HoursSpec, plan  # noqa: E402
from camera_viewer.hours_controller import SETTINGS_FOLDER_KEY, HoursExportController  # noqa: E402
from camera_viewer.hours_dialogs import HoursProgressDialog, HoursSelectDialog  # noqa: E402
from camera_viewer.hours_progress import PHASE_CANCELLED, PHASE_DONE, PHASE_FAILED, HoursProgress  # noqa: E402
from camera_viewer.progress_button import ProgressButton  # noqa: E402

DAY = date(2026, 9, 20)
GB = 1024 ** 3


def at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 9, 20, hour, minute, second)


def make_clips() -> dict[int, list[Clip]]:
    return {
        1: [Clip(1, at(8), at(20))],
        2: [Clip(2, at(8), at(20))],
        3: [Clip(3, at(9), at(12))],
        4: [Clip(4, at(8, 30), at(19, 30))],
    }


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class QtTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])


def make_spec(cells=None, folder="/tmp/x") -> HoursSpec:
    return HoursSpec(DAY, cells or {1: [9, 10], 2: [9]}, Path(folder), make_clips(), at(21))


class ProgressModelTests(QtTestCase):
    def setUp(self) -> None:
        self.clock = Clock()
        self.spec = make_spec()
        self.plans = plan(self.spec)
        self.model = HoursProgress(self.spec, self.plans, clock=self.clock)
        self.video1 = self.model.channel(1).video_pieces  # 2 horas = 60 trozos de 2 min

    def test_it_starts_queued_with_zero_progress(self) -> None:
        self.assertEqual(self.model.channels, [1, 2])
        self.assertEqual(self.model.overall_fraction(), 0.0)
        self.assertEqual(self.model.channel(1).phase, "queued")
        self.assertEqual(len(self.video1), 60)

    def test_download_events_move_the_channel_bar_by_finished_work_plus_the_current_piece(self) -> None:
        first = self.video1[0]
        self.model.apply(("piece", 1, first, at(9), at(9, 2)))
        self.model.apply(("progress", 1, first, 0))
        self.assertEqual(self.model.channel(1).phase, "downloading")
        self.assertEqual(self.model.piece_text(1), "09:00:00 · trozo 1 de 60")
        self.model.apply(("progress", 1, first, 4_000_000))  # de ≈ 31 MB esperados
        self.assertGreater(self.model.pieces_fraction(1), 0.0)
        before = self.model.fraction(1)
        for piece in self.video1[:30]:
            self.model.apply(("piece_done", 1, piece))
        self.assertAlmostEqual(self.model.pieces_fraction(1), 0.5, delta=0.02)
        self.assertGreater(self.model.fraction(1), before)
        self.assertLess(self.model.fraction(1), 0.93)  # descargar no es todo: falta unir

    def test_a_black_piece_weighs_almost_nothing(self) -> None:
        spec = HoursSpec(DAY, {3: [9, 10, 11]}, Path("/tmp/x"), {3: [Clip(3, at(9), at(9, 10)), Clip(3, at(11, 50), at(12))]}, at(21))
        model = HoursProgress(spec, plan(spec), clock=self.clock)
        item = model.channel(3)
        gaps = [i for i, p in enumerate(item.pieces) if p.kind == "gap"]
        for index in gaps:
            model.apply(("piece_done", 3, index))
        # 2 h 40 min de negro frente a 20 min de video: por tiempo serían el 89 %, por trabajo el 14 %
        self.assertLess(model.pieces_fraction(3), 0.2)

    def test_joining_and_final_states(self) -> None:
        self.model.apply(("state", 1, "Uniendo…", "joining"))
        self.assertEqual(self.model.fraction(1), 0.95)
        self.model.apply(("channel_done", 1, "/tmp/nope/a.mp4", "2 tramos sin grabación rellenos con negro"))
        self.assertEqual(self.model.channel(1).phase, PHASE_DONE)
        self.assertEqual(self.model.fraction(1), 1.0)
        self.assertIn("tramos", self.model.channel(1).note)
        self.model.apply(("channel_failed", 2, "Cancelado"))
        self.assertEqual(self.model.channel(2).phase, PHASE_CANCELLED)
        self.model.apply(("finished", {1: "/tmp/nope/a.mp4", 2: None}))
        self.assertTrue(self.model.finished)
        self.assertEqual((self.model.saved_count(), self.model.total_count()), (1, 2))
        self.assertTrue(self.model.was_cancelled())

    def test_failures_and_late_events_are_ignored_after_a_final_state(self) -> None:
        self.model.apply(("channel_failed", 1, "No hay grabaciones"))
        self.assertEqual(self.model.channel(1).phase, PHASE_FAILED)
        self.model.apply(("progress", 1, self.video1[0], 5))
        self.model.apply(("state", 1, "Descargando…", "downloading"))
        self.assertEqual(self.model.channel(1).phase, PHASE_FAILED)

    def test_paused_flag_and_warnings(self) -> None:
        self.model.apply(("paused", True))
        self.assertTrue(self.model.paused)
        self.model.apply(("warning", 1, "El trozo de las 09:12:00 no se pudo descargar"))
        self.assertEqual(self.model.warnings_count(), 1)
        self.model.apply(("finished", {}))
        self.assertFalse(self.model.paused)  # al terminar ya no está "en pausa"

    def test_speed_and_eta(self) -> None:
        first = self.video1[0]
        self.model.apply(("progress", 1, first, 0))
        for _ in range(10):
            self.clock.now += 1.0
            self.model.apply(("progress", 1, first, self.model.channel(1).piece_bytes[first] + 3_000_000))
        self.assertAlmostEqual(self.model.speed() / 3_000_000, 1.0, delta=0.2)
        self.model.apply(("piece_done", 1, first))
        for piece in self.video1[1:12]:
            self.model.apply(("piece_done", 1, piece))
        self.assertIsNotNone(self.model.overall_eta())
        self.model.apply(("paused", True))
        self.assertIsNone(self.model.overall_eta())  # en pausa no se promete nada
        self.assertIsNone(self.model.speed())

    def test_hours_text(self) -> None:
        self.assertEqual(self.model.hours_text(1), "09h, 10h")
        many = HoursProgress(make_spec({1: list(range(8, 20))}), plan(make_spec({1: list(range(8, 20))})), clock=self.clock)
        self.assertEqual(many.hours_text(1), "12 horas (08h a 20h)")


class CheckboxStyleTests(QtTestCase):
    def test_the_app_stylesheet_gives_checkboxes_a_light_border_so_they_show_on_the_dark_background(self) -> None:
        from camera_viewer.__main__ import DARK_STYLESHEET

        rule = DARK_STYLESHEET[DARK_STYLESHEET.index("QCheckBox::indicator {"):]
        rule = rule[: rule.index("}")]
        self.assertIn("border: 1px solid #9CA3AF", rule)  # claro, no el casi negro de Fusion
        for state in ("checked", "indeterminate", "disabled", "hover"):
            self.assertIn(f"QCheckBox::indicator:{state}", DARK_STYLESHEET)

    def test_a_checkbox_renders_a_light_border_pixel_with_the_real_stylesheet(self) -> None:
        from PySide6.QtWidgets import QCheckBox, QStyleFactory

        from camera_viewer.__main__ import DARK_STYLESHEET

        app = QApplication.instance()
        old_style, old_sheet = app.style().objectName(), app.styleSheet()
        self.addCleanup(lambda: (app.setStyleSheet(old_sheet), app.setStyle(QStyleFactory.create(old_style))))
        app.setStyle(QStyleFactory.create("Fusion"))
        app.setStyleSheet(DARK_STYLESHEET)
        check = QCheckBox()
        check.resize(24, 24)
        check.show()
        self.addCleanup(check.close)
        image = check.grab().toImage()
        colors = {image.pixelColor(x, y).name() for x in range(image.width()) for y in range(image.height())}
        self.assertIn("#9ca3af", colors)


class ProgressButtonTests(QtTestCase):
    def test_states_texts_and_clamped_fraction(self) -> None:
        button = ProgressButton("Exportar")
        self.assertEqual((button.state, button.text(), button.fraction), (progress_button.IDLE, "Exportar", 0.0))
        button.set_state(progress_button.RUNNING, "Exportando… 37 %", 0.37, "tip")
        self.assertEqual((button.text(), button.fraction, button.toolTip()), ("Exportando… 37 %", 0.37, "tip"))
        button.set_state(progress_button.PAUSED, "Pausado · 37 %", 5.0)
        self.assertEqual(button.fraction, 1.0)
        button.set_state(progress_button.IDLE)
        self.assertEqual((button.text(), button.fraction), ("Exportar", 0.0))  # vuelve a su texto de reposo

    def test_it_paints_the_fill_over_the_left_part(self) -> None:
        button = ProgressButton("Exportar")
        button.resize(200, 30)
        button.set_state(progress_button.RUNNING, "", 0.5)
        image = button.grab().toImage()
        left, right = image.pixelColor(50, 15), image.pixelColor(150, 15)
        self.assertNotEqual(left.name(), right.name())  # la mitad rellena se distingue de la vacía


class SelectDialogTests(QtTestCase):
    def open(self, free=lambda folder: 500 * GB, clips=None, folder="/tmp") -> HoursSelectDialog:
        dialog = HoursSelectDialog(DAY, clips or make_clips(), at(21), Path(folder), free_bytes=free)
        dialog.show()
        self.addCleanup(dialog.close)
        return dialog

    def test_only_hours_with_recording_can_be_chosen(self) -> None:
        dialog = self.open()
        self.assertTrue(dialog.cells[(1, 8)].isEnabled())
        self.assertFalse(dialog.cells[(1, 7)].isEnabled())  # nada grabado a las 07
        self.assertFalse(dialog.cells[(1, 20)].isEnabled())
        self.assertFalse(dialog.cells[(3, 8)].isEnabled())  # CAM 3 grabó de 09 a 12
        self.assertTrue(dialog.cells[(3, 9)].isEnabled())
        self.assertFalse(dialog.cells[(3, 12)].isEnabled())
        self.assertIn("Sin grabación", dialog.cells[(3, 12)].toolTip())

    def test_nothing_is_selected_at_first_and_export_is_disabled_with_a_hint(self) -> None:
        dialog = self.open()
        self.assertEqual(dialog.selection(), {})
        self.assertFalse(dialog._export.isEnabled())
        self.assertIn("al menos una hora", dialog._summary.text())

    def test_a_cell_a_row_a_column_and_the_whole_day(self) -> None:
        dialog = self.open()
        dialog.cells[(1, 9)].setChecked(True)
        self.assertEqual(dialog.selection(), {1: [9]})
        dialog._toggle_hour(10)  # toda la fila: los canales con grabación a las 10
        self.assertEqual(dialog.selection(), {1: [9, 10], 2: [10], 3: [10], 4: [10]})
        dialog._toggle_hour(10)  # otra vez: se quita
        self.assertEqual(dialog.selection(), {1: [9]})
        dialog._toggle_channel(2)  # toda la columna de CAM 2
        self.assertEqual(dialog.selection()[2], list(range(8, 20)))
        dialog._set_all(True)
        self.assertEqual(dialog.selection()[3], [9, 10, 11])
        self.assertEqual(dialog.selection()[4], list(range(8, 20)))  # 08:30 a 19:30: las 08 y las 19 incluidas
        dialog._set_all(False)
        self.assertEqual(dialog.selection(), {})

    def test_header_checks_show_none_some_or_all(self) -> None:
        dialog = self.open()
        self.assertEqual(dialog.channel_checks[1].checkState(), Qt.CheckState.Unchecked)
        dialog.cells[(1, 9)].setChecked(True)
        self.assertEqual(dialog.channel_checks[1].checkState(), Qt.CheckState.PartiallyChecked)
        dialog._toggle_channel(1)
        self.assertEqual(dialog.channel_checks[1].checkState(), Qt.CheckState.Checked)
        self.assertEqual(dialog.hour_checks[9].checkState(), Qt.CheckState.PartiallyChecked)  # solo CAM 1
        self.assertFalse(dialog.hour_checks[5].isEnabled())  # ninguna cámara grabó a las 05

    def test_the_summary_shows_channels_size_free_space_and_time(self) -> None:
        dialog = self.open()
        dialog._toggle_hour(9)
        text = dialog._summary.text()
        self.assertIn("4 canales", text)
        self.assertIn("4.0 h de video", text)
        self.assertIn("GB" if False else "libre en disco", text)
        self.assertIn("tardaría", text)
        self.assertTrue(dialog._export.isEnabled())
        total, needed, video, channels = dialog.estimate()
        self.assertGreater(needed, total)  # con los temporales del canal en curso
        self.assertEqual((video, channels), (4 * 3600, 4))

    def test_when_it_does_not_fit_it_says_so_and_blocks_the_export(self) -> None:
        dialog = self.open(free=lambda folder: 1 * GB)
        dialog._set_all(True)
        self.assertIn("No cabe", dialog._summary.text())
        self.assertFalse(dialog._export.isEnabled())
        dialog._set_all(False)
        dialog.cells[(1, 9)].setChecked(True)  # una hora de un canal ≈ 0.9 GB + temporales > 1 GB libre
        self.assertIn("No cabe", dialog._summary.text())

    def test_the_folder_field_is_validated_and_browse_fills_it(self) -> None:
        dialog = self.open()
        dialog._toggle_hour(9)
        dialog._folder_edit.textEdited.emit("relativa")
        self.assertFalse(dialog._export.isEnabled())
        self.assertIn("carpeta no es válida", dialog._summary.text())
        self.assertIn("EF4444", dialog._folder_edit.styleSheet())
        good = tempfile.mkdtemp()
        dialog._folder_edit.textEdited.emit(good)
        self.assertTrue(dialog._export.isEnabled())
        self.assertEqual(dialog.folder(), Path(good))
        self.assertEqual(dialog._folder_edit.styleSheet(), "")

    def test_spec_carries_selection_folder_clips_and_day(self) -> None:
        dialog = self.open(folder="/tmp")
        dialog._toggle_hour(9)
        spec = dialog.spec()
        self.assertEqual((spec.day, spec.folder, spec.now), (DAY, Path("/tmp"), at(21)))
        self.assertEqual(spec.cells, {1: [9], 2: [9], 3: [9], 4: [9]})
        self.assertIs(spec.clips, dialog._clips)

    def test_export_button_accepts_the_dialog(self) -> None:
        dialog = self.open()
        dialog._toggle_hour(9)
        dialog._export.click()
        self.assertEqual(dialog.result(), HoursSelectDialog.DialogCode.Accepted)


class ProgressDialogTests(QtTestCase):
    def setUp(self) -> None:
        self.clock = Clock()
        self.spec = make_spec()
        self.model = HoursProgress(self.spec, plan(self.spec), clock=self.clock)
        self.asked: list[str] = []
        self.answer = True
        self.panel = HoursProgressDialog(self.model, confirm_cancel=lambda text: self.asked.append(text) or self.answer)
        self.panel.show()
        self.addCleanup(self.panel._timer.stop)
        self.cancels: list[int] = []
        self.panel.cancel_requested.connect(lambda: self.cancels.append(1))
        self.dismissed: list[int] = []
        self.panel.dismissed.connect(lambda: self.dismissed.append(1))

    def test_one_card_per_channel_and_only_cancel_at_first(self) -> None:
        self.assertEqual(sorted(self.panel.cards), [1, 2])
        self.assertTrue(self.panel._cancel.isVisible())
        self.assertFalse(self.panel._open_folder.isVisible())
        self.assertEqual(self.panel.cards[1]._phase.text(), "En cola")

    def test_cards_and_overall_follow_the_model(self) -> None:
        piece = self.model.channel(1).video_pieces[0]
        self.model.apply(("piece", 1, piece, at(9), at(9, 2)))
        self.model.apply(("progress", 1, piece, 8_000_000))
        self.model.changed.emit()
        card = self.panel.cards[1]
        self.assertEqual(card._phase.text(), "Descargando del DVR")
        self.assertIn("09:00:00", card._detail.text())
        self.assertIn("trozo 1 de 60", card._detail.text())
        self.assertGreater(self.panel._overall.value(), 0)
        self.assertEqual(self.panel.cards[2]._phase.text(), "En cola")

    def test_a_pause_is_shown_on_the_panel_and_the_card(self) -> None:
        piece = self.model.channel(1).video_pieces[0]
        self.model.apply(("progress", 1, piece, 1))
        self.model.apply(("paused", True))
        self.model.changed.emit()
        self.assertTrue(self.panel._pause_note.isVisible())
        self.assertEqual(self.panel.cards[1]._phase.text(), "En pausa")
        self.assertEqual(self.panel._headline.text(), "En pausa")
        self.model.apply(("paused", False))
        self.model.changed.emit()
        self.assertFalse(self.panel._pause_note.isVisible())

    def test_warnings_are_listed_in_the_card(self) -> None:
        self.model.apply(("warning", 1, "El trozo de las 09:12:00 no se pudo descargar del DVR; se rellena con negro."))
        self.model.changed.emit()
        self.assertTrue(self.panel.cards[1]._warnings.isVisible())
        self.assertIn("09:12:00", self.panel.cards[1]._warnings.text())

    def test_cancel_asks_only_when_something_was_downloaded(self) -> None:
        self.panel._cancel.click()
        self.assertEqual(self.asked, [])
        self.assertEqual(self.cancels, [1])
        self.assertEqual(self.panel._cancel.text(), "Cancelando…")

    def test_cancel_with_data_can_be_declined(self) -> None:
        self.model.apply(("progress", 1, self.model.channel(1).video_pieces[0], 5 * 1024 * 1024))
        self.answer = False
        self.panel._cancel.click()
        self.assertEqual(self.asked, ["5.0 MB"])
        self.assertEqual(self.cancels, [])
        self.assertFalse(self.model.cancelling)

    def test_closing_the_panel_while_exporting_only_hides_it(self) -> None:
        self.panel.close()
        self.assertFalse(self.panel.isVisible())
        self.assertEqual(self.dismissed, [])
        self.assertFalse(self.model.cancelling)  # la exportación sigue

    def test_finished_all_shows_open_folder_and_closing_dismisses(self) -> None:
        self.model.apply(("channel_done", 1, "/tmp/nope/CAM1_x.mp4", None))
        self.model.apply(("channel_done", 2, "/tmp/nope/CAM2_x.mp4", "1 tramo sin grabación relleno con negro"))
        self.model.apply(("finished", {}))
        self.model.changed.emit()
        self.assertIn("Listo", self.panel._headline.text())
        self.assertFalse(self.panel._cancel.isVisible())
        self.assertTrue(self.panel._open_folder.isVisible())
        self.assertIn("tramo sin grabación", self.panel.cards[2]._detail.text())
        self.panel._close.click()
        self.assertEqual(self.dismissed, [1])

    def test_partial_and_cancelled_results(self) -> None:
        self.model.apply(("channel_done", 1, "/tmp/nope/CAM1_x.mp4", None))
        self.model.apply(("channel_failed", 2, "Cancelado"))
        self.model.apply(("finished", {}))
        self.model.changed.emit()
        self.assertIn("Cancelado: se guardaron 1 de 2", self.panel._headline.text())
        self.assertEqual(self.panel._overall.format(), "1 de 2 canales guardados")
        self.assertEqual(self.panel.cards[2]._phase.text(), "Cancelado")


class FakeHours:
    """Motor falso: una cola de avisos, cancel() y finished()."""

    def __init__(self) -> None:
        self.events: queue.Queue = queue.Queue()
        self.cancelled = False
        self.thread = None
        self._finished = False

    def cancel(self) -> None:
        self.cancelled = True

    def finished(self) -> bool:
        return self._finished

    def push(self, *event) -> None:
        self.events.put(event)
        if event[0] == "finished":
            self._finished = True


class FakeSelect:
    accept = True
    last = None

    def __init__(self, day, clips, now, folder, parent=None) -> None:
        FakeSelect.last = self
        self.day, self.clips, self.now, self.initial_folder = day, clips, now, folder
        self._folder = Path("/tmp/elegida")

    def exec(self) -> int:
        return 1 if FakeSelect.accept else 0

    def folder(self) -> Path:
        return self._folder

    def spec(self) -> HoursSpec:
        return HoursSpec(self.day, {1: [9], 2: [9]}, self._folder, self.clips, self.now)


class ControllerTests(QtTestCase):
    def setUp(self) -> None:
        FakeSelect.accept, FakeSelect.last = True, None
        self.button = ProgressButton("Exportar")
        self.window = QApplication.activeWindow() or __import__("PySide6.QtWidgets", fromlist=["QWidget"]).QWidget()
        self.messages: list[str] = []
        self.engine = FakeHours()
        self.started: list[tuple] = []
        self.clips = make_clips()
        self.day: date | None = DAY
        self.saved: dict = {}

        class Settings:
            def value(inner, key, default=None):
                return self.saved.get(key, default)

            def setValue(inner, key, value) -> None:
                self.saved[key] = value

        def starter(host, user, password, spec):
            self.started.append((host, user, password, spec))
            return self.engine

        self.opened: list[Path] = []
        self.controller = HoursExportController(
            self.button, self.window, clips_provider=lambda: self.clips, day_provider=lambda: self.day,
            credentials=lambda: ("dvr", "u", "p"), notify=self.messages.append, settings=Settings(), now=lambda: at(21),
            starter=starter, select_factory=FakeSelect, confirm_cancel=lambda text: True, open_folder=self.opened.append,
        )
        self.addCleanup(self.controller._timer.stop)

    def start(self) -> None:
        self.button.click()

    def pump(self) -> None:
        self.controller._poll()

    def test_idle_button_opens_the_selection_and_starts_the_export_with_the_credentials(self) -> None:
        self.assertEqual(self.button.state, progress_button.IDLE)
        self.start()
        self.assertEqual(FakeSelect.last.day, DAY)
        self.assertEqual(len(self.started), 1)
        host, user, password, spec = self.started[0]
        self.assertEqual((host, user, password), ("dvr", "u", "p"))
        self.assertEqual(spec.cells, {1: [9], 2: [9]})
        self.assertEqual(self.button.state, progress_button.RUNNING)
        self.assertEqual(self.saved[SETTINGS_FOLDER_KEY], "/tmp/elegida")  # se recuerda la carpeta
        self.assertTrue(self.controller.is_running())

    def test_it_remembers_the_folder_for_next_time(self) -> None:
        self.saved[SETTINGS_FOLDER_KEY] = "/tmp/anterior"
        self.start()
        self.assertEqual(FakeSelect.last.initial_folder, Path("/tmp/anterior"))

    def test_cancelling_the_selection_starts_nothing(self) -> None:
        FakeSelect.accept = False
        self.start()
        self.assertEqual(self.started, [])
        self.assertEqual(self.button.state, progress_button.IDLE)

    def test_no_day_or_no_recordings_explains_instead_of_opening(self) -> None:
        self.day = None
        self.start()
        self.assertIn("Selecciona primero un día", self.messages[-1])
        self.day, self.clips = DAY, {1: [], 2: []}
        self.start()
        self.assertIn("No hay grabaciones", self.messages[-1])
        self.assertIsNone(FakeSelect.last)

    def test_the_button_becomes_the_progress_bar(self) -> None:
        self.start()
        piece = self.controller.progress.channel(1).video_pieces[0]
        self.engine.push("piece", 1, piece, at(9), at(9, 2))
        self.engine.push("progress", 1, piece, 20 * 1024 * 1024)
        self.pump()
        self.assertEqual(self.button.state, progress_button.RUNNING)
        self.assertGreater(self.button.fraction, 0.0)
        self.assertIn("Exportando…", self.button.text())
        self.assertIn("%", self.button.text())

    def test_a_live_view_pauses_the_button_and_resuming_restores_it(self) -> None:
        self.start()
        self.engine.push("paused", True)
        self.pump()
        self.assertEqual(self.button.state, progress_button.PAUSED)
        self.assertIn("Pausado", self.button.text())
        self.engine.push("paused", False)
        self.pump()
        self.assertEqual(self.button.state, progress_button.RUNNING)

    def test_clicking_while_exporting_opens_the_progress_panel_only_once(self) -> None:
        self.start()
        self.button.click()
        panel = self.controller.panel
        self.assertIsNotNone(panel)
        self.assertTrue(panel.isVisible())
        panel.hide()
        self.button.click()
        self.assertIs(self.controller.panel, panel)  # el mismo panel, no otro
        self.assertTrue(panel.isVisible())
        self.assertEqual(len(self.started), 1)  # y no vuelve a abrir la selección
        panel.hide()
        self.addCleanup(panel._timer.stop)

    def test_cancel_from_the_panel_cancels_the_engine(self) -> None:
        self.start()
        self.button.click()
        self.controller.panel._cancel.click()
        self.assertTrue(self.engine.cancelled)
        self.assertEqual(self.button.text(), "Cancelando…")
        self.controller.panel.hide()

    def test_finishing_shows_the_result_on_the_button_and_notifies(self) -> None:
        self.start()
        self.engine.push("channel_done", 1, "/tmp/nope/a.mp4", None)
        self.engine.push("channel_done", 2, "/tmp/nope/b.mp4", None)
        self.engine.push("finished", {})
        self.pump()
        self.assertEqual((self.button.state, self.button.text(), self.button.fraction), (progress_button.DONE, "Exportación lista", 1.0))
        self.assertIn("Exportación lista: 2 archivos", self.messages[-1])
        self.assertFalse(self.controller.is_running())
        self.assertTrue(self.controller.is_active())  # el resultado sigue esperando a que lo veas

    def test_partial_and_failed_results_use_the_error_color(self) -> None:
        self.start()
        self.engine.push("channel_done", 1, "/tmp/nope/a.mp4", None)
        self.engine.push("channel_failed", 2, "No se pudo descargar")
        self.engine.push("finished", {})
        self.pump()
        self.assertEqual(self.button.state, progress_button.ERROR)
        self.assertIn("parcial (1/2)", self.button.text())
        self.assertIn("problemas", self.messages[-1])

    def test_closing_the_panel_of_a_finished_export_returns_the_button_to_idle_and_allows_a_new_one(self) -> None:
        self.start()
        self.engine.push("channel_done", 1, "/tmp/nope/a.mp4", None)
        self.engine.push("channel_done", 2, "/tmp/nope/b.mp4", None)
        self.engine.push("finished", {})
        self.pump()
        self.button.click()
        self.controller.panel._close.click()
        self.assertEqual(self.button.state, progress_button.IDLE)
        self.assertEqual(self.button.text(), "Exportar")
        self.assertFalse(self.controller.is_active())
        self.engine = FakeHours()
        self.start()  # se puede exportar otra vez
        self.assertEqual(len(self.started), 2)

    def test_open_folder_from_the_panel(self) -> None:
        self.start()
        self.engine.push("channel_done", 1, "/tmp/nope/a.mp4", None)
        self.engine.push("finished", {})
        self.pump()
        self.button.click()
        self.controller.panel._open_folder.click()
        self.assertEqual(self.opened, [Path("/tmp/elegida")])
        self.controller.panel.close()

    def test_shutdown_cancels_the_engine(self) -> None:
        self.start()
        self.controller.shutdown()
        self.assertTrue(self.engine.cancelled)


if __name__ == "__main__":
    unittest.main()
