"""La fila única de botones (controles + marcas del clip) y las horas de las marcas sobre la línea de
tiempo del día. Correr desde v_2/: .venv/bin/python -m unittest camera_viewer.tests.test_controls_row -v"""
from __future__ import annotations

import os
import unittest
from datetime import date, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize, Qt  # noqa: E402
from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication, QGraphicsLineItem, QGraphicsRectItem, QGraphicsSimpleTextItem, QPushButton, QWidget  # noqa: E402

from camera_viewer import icons  # noqa: E402
from camera_viewer.button_group import BUTTON_GAP, fuse_buttons  # noqa: E402
from camera_viewer.export_bar import IDLE, PREVIEW, ExportBar  # noqa: E402
from camera_viewer.playback_controls import PlaybackControls  # noqa: E402
from camera_viewer.timeline_widget import SECONDS_PER_DAY, TimelineWidget  # noqa: E402

DAY = date(2026, 9, 20)


def at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 9, 20, hour, minute, second)


class QtTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])


class IconTests(QtTestCase):
    def test_every_icon_has_a_drawn_pixmap_for_normal_on_and_disabled(self) -> None:
        for make in (icons.pause_icon, icons.play_icon, icons.reverse_icon, icons.mark_start_icon, icons.mark_end_icon):
            icon = make()
            self.assertFalse(icon.isNull())
            for mode, state in ((QIcon.Mode.Normal, QIcon.State.Off), (QIcon.Mode.Normal, QIcon.State.On), (QIcon.Mode.Disabled, QIcon.State.Off)):
                image = icon.pixmap(icons.ICON_SIZE, mode, state).toImage()
                opaque = sum(1 for x in range(image.width()) for y in range(image.height()) if image.pixelColor(x, y).alpha() > 128)
                self.assertGreater(opaque, 20, f"{make.__name__} {mode} {state} salió vacío")

    def test_the_two_brackets_are_mirror_images(self) -> None:
        size = QSize(icons.GRID, icons.GRID)  # el tamaño lógico del dibujo: sin reescalado que rompa la simetría
        left = icons.mark_start_icon().pixmap(size).toImage()
        right = icons.mark_end_icon().pixmap(size).toImage()
        self.assertNotEqual(left, right)
        self.assertEqual(left.flipped(Qt.Orientation.Horizontal), right)


class FuseTests(QtTestCase):
    def test_fused_buttons_touch_and_lose_the_radius_and_border_where_they_meet(self) -> None:
        buttons = [QPushButton("a"), QPushButton("b"), QPushButton("c")]
        group = fuse_buttons(buttons)
        self.assertEqual(group.layout().spacing(), 0)
        self.assertEqual([group.layout().itemAt(i).widget() for i in range(3)], buttons)
        first, middle, last = (b.styleSheet() for b in buttons)
        self.assertIn("border-top-right-radius: 0px", first)
        self.assertNotIn("left-radius", first)
        self.assertIn("border-top-left-radius: 0px", middle)
        self.assertIn("border-top-right-radius: 0px", middle)
        self.assertIn("border-left-width: 0px", middle)
        self.assertIn("border-top-left-radius: 0px", last)
        self.assertNotIn("right-radius", last)

    def test_a_reverse_style_already_on_a_button_is_kept(self) -> None:
        button = QPushButton("x")
        button.setStyleSheet("QPushButton:checked { color: red; }")
        group = fuse_buttons([QPushButton("a"), button])  # (el grupo es dueño de los botones: hay que conservarlo)
        self.assertIn(":checked", button.styleSheet())
        self.assertIsNotNone(group)


class PlaybackControlsTests(QtTestCase):
    def setUp(self) -> None:
        self.controls = PlaybackControls()
        self.controls.set_active(True)

    def test_pause_is_an_icon_that_turns_into_play_when_paused(self) -> None:
        self.assertEqual(self.controls._pause.text(), "")
        self.assertFalse(self.controls._pause.icon().isNull())
        self.assertEqual(self.controls._pause.toolTip(), "Pausar")
        before = self.controls._pause.icon().pixmap(icons.ICON_SIZE).toImage()
        self.controls.set_paused(True)
        self.assertEqual(self.controls._pause.toolTip(), "Reanudar")
        self.assertNotEqual(self.controls._pause.icon().pixmap(icons.ICON_SIZE).toImage(), before)

    def test_reverse_is_an_icon_button_that_lights_up_while_playing_backwards(self) -> None:
        button = self.controls._direction
        self.assertEqual(button.text(), "")
        self.assertFalse(button.icon().isNull())
        self.assertTrue(button.isCheckable())
        self.assertFalse(button.isChecked())
        self.controls.set_reverse(True)
        self.assertTrue(button.isChecked())  # el estilo :checked lo enciende en azul
        self.assertIn(":checked", button.styleSheet())
        self.assertIn("reversa", button.toolTip().lower())
        self.controls.set_reverse(False)
        self.assertFalse(button.isChecked())

    def test_the_speed_buttons_are_one_fused_group(self) -> None:
        slower, current, faster = self.controls._slower, self.controls._speed_button, self.controls._faster
        group = slower.parentWidget()
        self.assertIs(current.parentWidget(), group)
        self.assertIs(faster.parentWidget(), group)
        self.assertEqual(group.layout().spacing(), 0)
        self.assertIn("border-top-right-radius: 0px", slower.styleSheet())
        self.assertIn("border-top-left-radius: 0px", faster.styleSheet())
        self.assertNotIn("right-radius", faster.styleSheet())

    def test_the_speed_buttons_still_work(self) -> None:
        seen = []
        self.controls.speed_selected.connect(seen.append)
        self.controls._faster.click()
        self.controls._slower.click()
        self.assertEqual(seen, [1.5, 0.5])

    def test_a_widget_can_be_added_at_the_end_of_the_row(self) -> None:
        extra = QWidget()
        self.controls.set_trailing_widget(extra)
        self.assertTrue(self.controls.isAncestorOf(extra))


class ConsistentGapTests(QtTestCase):
    def test_every_gap_in_the_row_is_the_same_as_between_the_first_three_buttons(self) -> None:
        controls = PlaybackControls(with_restart=True)
        bar = ExportBar((1, 2, 3, 4), compact=True)
        controls.set_trailing_widget(bar)
        self.assertEqual(BUTTON_GAP, 6)
        self.assertEqual(controls.layout().spacing(), BUTTON_GAP)
        self.assertEqual(bar.layout().spacing(), BUTTON_GAP)
        layout = controls.layout()
        spacers = [layout.itemAt(i) for i in range(layout.count()) if layout.itemAt(i).spacerItem() is not None]
        self.assertEqual(len(spacers), 2)  # solo los dos extremos que centran la fila: ya no hay huecos de otro tamaño
        controls.show()
        self.addCleanup(controls.close)
        self.app.processEvents()
        widgets = [layout.itemAt(i).widget() or layout.itemAt(i).layout().itemAt(0).widget() for i in range(layout.count())
                   if layout.itemAt(i).spacerItem() is None]
        gaps = {right.geometry().left() - left.geometry().right() - 1 for left, right in zip(widgets, widgets[1:])}
        self.assertEqual(gaps, {BUTTON_GAP})


class CompactExportBarTests(QtTestCase):
    def setUp(self) -> None:
        self.bar = ExportBar((1, 2, 3, 4), compact=True)
        self.bar.set_active(True)
        self.bar.show()
        self.addCleanup(self.bar.close)

    def test_start_and_end_are_icons_and_only_the_four_buttons_show(self) -> None:
        for button in (self.bar._mark_start, self.bar._mark_end):
            self.assertEqual(button.text(), "")
            self.assertFalse(button.icon().isNull())
            self.assertTrue(button.toolTip())
            self.assertTrue(button.isVisible())
        self.assertTrue(self.bar._save.isVisible() and self.bar._save_last.isVisible())
        for hidden in (self.bar._range_label, self.bar._clear, self.bar._confirm, self.bar._folder_edit):
            self.assertFalse(hidden.isVisible())

    def test_start_end_and_save_clip_are_one_fused_group_and_save_last_is_apart(self) -> None:
        group = self.bar._mark_start.parentWidget()
        self.assertIs(self.bar._mark_end.parentWidget(), group)
        self.assertIs(self.bar._save.parentWidget(), group)
        self.assertIsNot(self.bar._save_last.parentWidget(), group)
        self.assertEqual(group.layout().spacing(), 0)
        self.assertIn("border-top-right-radius: 0px", self.bar._mark_start.styleSheet())
        self.assertIn("border-top-left-radius: 0px", self.bar._save.styleSheet())

    def test_it_stays_idle_and_shows_nothing_in_any_other_state(self) -> None:
        self.assertEqual(self.bar.state, IDLE)
        self.bar.set_state(PREVIEW)
        self.assertFalse(any(w.isVisible() for w in (self.bar._mark_start, self._save_button(), self.bar._save_last)))

    def _save_button(self) -> QPushButton:
        return self.bar._save

    def test_save_clip_needs_both_marks(self) -> None:
        self.assertFalse(self.bar._save.isEnabled())
        self.bar.set_marks(True, "")
        self.assertTrue(self.bar._save.isEnabled())
        self.bar.set_marks(False, "")
        self.assertFalse(self.bar._save.isEnabled())

    def test_the_signals_are_the_same_as_ever(self) -> None:
        seen = []
        self.bar.mark_start_clicked.connect(lambda: seen.append("start"))
        self.bar.mark_end_clicked.connect(lambda: seen.append("end"))
        self.bar.save_last_clicked.connect(lambda: seen.append("last"))
        self.bar.set_marks(True, "")
        self.bar.save_clicked.connect(lambda: seen.append("save"))
        for button in (self.bar._mark_start, self.bar._mark_end, self.bar._save, self.bar._save_last):
            button.click()
        self.assertEqual(seen, ["start", "end", "save", "last"])


class DayTimelineMarkTests(QtTestCase):
    def setUp(self) -> None:
        self.tl = TimelineWidget()
        self.tl.resize(1200, 90)
        self.tl.show()
        self.addCleanup(self.tl.close)
        self.tl.set_day(DAY)
        self.app.processEvents()

    def labels(self) -> list[QGraphicsSimpleTextItem]:
        return [item for item in self.tl._range_items if isinstance(item, QGraphicsSimpleTextItem)]

    def band(self) -> QGraphicsRectItem | None:
        return next((item for item in self.tl._range_items if isinstance(item, QGraphicsRectItem)), None)

    def test_both_marks_draw_the_band_with_both_times(self) -> None:
        self.tl.set_marks(at(8, 16, 20), at(8, 29, 57))
        self.assertEqual(self.tl._export_range, (at(8, 16, 20), at(8, 29, 57)))
        self.assertIsNotNone(self.band())
        self.assertEqual(sorted(label.text() for label in self.labels()), ["08:16:20", "08:29:57"])

    def test_at_full_day_zoom_the_times_go_outside_the_narrow_band(self) -> None:
        self.tl.set_marks(at(8, 16, 20), at(8, 29, 57))
        band = self.band().rect()
        start_label = next(label for label in self.labels() if label.text() == "08:16:20")
        end_label = next(label for label in self.labels() if label.text() == "08:29:57")
        self.assertLess(start_label.x(), band.left())  # a la izquierda del inicio
        self.assertGreater(end_label.x(), band.right())  # a la derecha del fin

    def test_zoomed_in_the_times_move_inside_the_band(self) -> None:
        self.tl.set_marks(at(8, 16, 20), at(8, 29, 57))
        self.tl._zoom = 60
        self.tl._update_transform()
        band = self.band().rect()
        start_label = next(label for label in self.labels() if label.text() == "08:16:20")
        end_label = next(label for label in self.labels() if label.text() == "08:29:57")
        self.assertGreaterEqual(start_label.x(), band.left())
        self.assertLess(start_label.x(), band.right())
        self.assertGreater(end_label.x(), band.left())
        self.assertLess(end_label.x(), band.right())

    def test_a_single_mark_is_a_line_with_its_time(self) -> None:
        self.tl.set_marks(at(8, 16, 20), None)
        self.assertIsNone(self.band())
        self.assertEqual([label.text() for label in self.labels()], ["08:16:20"])
        line = next(item for item in self.tl._range_items if isinstance(item, QGraphicsLineItem))
        self.assertGreater(self.labels()[0].x(), line.line().x1())  # el inicio: la hora a su derecha
        self.tl.set_marks(None, at(8, 29, 57))
        self.assertEqual([label.text() for label in self.labels()], ["08:29:57"])
        line = next(item for item in self.tl._range_items if isinstance(item, QGraphicsLineItem))
        self.assertLess(self.labels()[0].x(), line.line().x1())  # el fin: la hora a su izquierda

    def test_clearing_removes_everything(self) -> None:
        self.tl.set_marks(at(8, 16, 20), at(8, 29, 57))
        self.tl.set_marks(None, None)
        self.assertEqual(self.tl._range_items, [])
        self.assertIsNone(self.tl._export_range)
        self.tl.set_export_range(at(9), at(10))  # la interfaz de siempre sigue valiendo
        self.assertIsNotNone(self.band())
        self.tl.clear_export_range()
        self.assertEqual(self.tl._range_items, [])

    def test_labels_never_leave_the_day(self) -> None:
        self.tl.set_marks(at(0, 0, 2), at(23, 59, 58))
        for label in self.labels():
            self.assertGreaterEqual(label.x(), 0)
            self.assertLessEqual(label.x(), SECONDS_PER_DAY)

    def test_changing_day_redraws_without_stale_items(self) -> None:
        self.tl.set_marks(at(8, 16, 20), at(8, 29, 57))
        self.tl.set_day(date(2026, 9, 21))  # otro día: la escena se limpia
        self.tl.set_marks(None, None)
        self.assertEqual(self.tl._range_items, [])

    def test_marks_from_another_day_draw_nothing_for_a_single_mark(self) -> None:
        self.tl.set_marks(datetime(2026, 9, 25, 8, 0, 0), None)
        self.assertEqual(self.labels(), [])


if __name__ == "__main__":
    unittest.main()
