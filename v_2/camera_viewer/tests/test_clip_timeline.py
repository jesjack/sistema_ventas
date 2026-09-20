"""Línea de tiempo propia de la ventana de guardado. Correr desde v_2/:
.venv/bin/python -m unittest camera_viewer.tests.test_clip_timeline -v"""
from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from camera_viewer.clip import Clip  # noqa: E402
from camera_viewer.clip_timeline import ClipTimeline, label_positions  # noqa: E402

T0 = datetime(2026, 9, 19, 10, 0, 0)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def mouse(widget, kind, x: float) -> None:
    event = QMouseEvent(kind, QPointF(x, 40), QPointF(x, 40), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    {"press": widget.mousePressEvent, "move": widget.mouseMoveEvent, "release": widget.mouseReleaseEvent}[
        {QMouseEvent.Type.MouseButtonPress: "press", QMouseEvent.Type.MouseMove: "move", QMouseEvent.Type.MouseButtonRelease: "release"}[kind]
    ](event)


class ClipTimelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.tl = ClipTimeline()
        self.tl.resize(1002, 74)  # 1000 px útiles: 1 px = 0.06 s con 60 s de contexto
        self.tl.set_context(at(0), at(60))
        self.tl.set_export_range(at(10), at(40))
        self.seeks, self.ranges = [], []
        self.tl.seek_requested.connect(self.seeks.append)
        self.tl.range_changed.connect(lambda a, b: self.ranges.append((a, b)))

    def test_time_and_position_convert_both_ways(self) -> None:
        self.assertAlmostEqual(self.tl.time_to_x(at(0)), 1.0)
        self.assertAlmostEqual(self.tl.time_to_x(at(60)), 1001.0)
        for seconds in (0, 7.5, 30, 59.9):
            self.assertAlmostEqual((self.tl.x_to_time(self.tl.time_to_x(at(seconds))) - at(seconds)).total_seconds(), 0.0, places=3)
        self.assertEqual(self.tl.x_to_time(-50), at(0))  # fuera de la barra se queda en el borde
        self.assertEqual(self.tl.x_to_time(5000), at(60))

    def test_clicking_the_bar_asks_to_seek_there(self) -> None:
        mouse(self.tl, QMouseEvent.Type.MouseButtonPress, self.tl.time_to_x(at(25)))
        mouse(self.tl, QMouseEvent.Type.MouseButtonRelease, self.tl.time_to_x(at(25)))
        self.assertEqual(len(self.seeks), 1)
        self.assertAlmostEqual((self.seeks[0] - at(25)).total_seconds(), 0.0, delta=0.1)
        self.assertEqual(self.ranges, [])

    def test_dragging_on_the_bar_scrubs(self) -> None:
        mouse(self.tl, QMouseEvent.Type.MouseButtonPress, self.tl.time_to_x(at(20)))
        mouse(self.tl, QMouseEvent.Type.MouseMove, self.tl.time_to_x(at(28)))
        mouse(self.tl, QMouseEvent.Type.MouseMove, self.tl.time_to_x(at(35)))
        mouse(self.tl, QMouseEvent.Type.MouseButtonRelease, self.tl.time_to_x(at(35)))
        self.assertEqual(len(self.seeks), 3)

    def test_grabbing_the_start_handle_and_dragging_changes_the_range(self) -> None:
        start_x = self.tl.time_to_x(at(10))
        mouse(self.tl, QMouseEvent.Type.MouseButtonPress, start_x + 3)  # cerca del asa
        mouse(self.tl, QMouseEvent.Type.MouseMove, self.tl.time_to_x(at(4)))
        mouse(self.tl, QMouseEvent.Type.MouseButtonRelease, self.tl.time_to_x(at(4)))
        self.assertEqual(self.seeks, [])  # agarrar un asa no mueve la reproducción
        start, end = self.ranges[0]
        self.assertAlmostEqual((start - at(4)).total_seconds(), 0.0, delta=0.1)
        self.assertEqual(end, at(40))

    def test_dragging_the_end_handle(self) -> None:
        mouse(self.tl, QMouseEvent.Type.MouseButtonPress, self.tl.time_to_x(at(40)) - 2)
        mouse(self.tl, QMouseEvent.Type.MouseMove, self.tl.time_to_x(at(52)))
        mouse(self.tl, QMouseEvent.Type.MouseButtonRelease, self.tl.time_to_x(at(52)))
        self.assertAlmostEqual((self.ranges[0][1] - at(52)).total_seconds(), 0.0, delta=0.1)
        self.assertEqual(self.ranges[0][0], at(10))

    def test_the_handles_cannot_cross_and_keep_at_least_one_second(self) -> None:
        mouse(self.tl, QMouseEvent.Type.MouseButtonPress, self.tl.time_to_x(at(10)))
        mouse(self.tl, QMouseEvent.Type.MouseMove, self.tl.time_to_x(at(55)))  # más allá del fin
        mouse(self.tl, QMouseEvent.Type.MouseButtonRelease, self.tl.time_to_x(at(55)))
        start, end = self.ranges[0]
        self.assertEqual((start, end), (at(39), at(40)))

    def test_releasing_a_handle_without_moving_it_changes_nothing(self) -> None:
        mouse(self.tl, QMouseEvent.Type.MouseButtonPress, self.tl.time_to_x(at(10)))
        mouse(self.tl, QMouseEvent.Type.MouseButtonRelease, self.tl.time_to_x(at(10)))
        self.assertEqual(self.ranges, [])

    def test_a_click_far_from_the_handles_seeks_instead_of_dragging_them(self) -> None:
        mouse(self.tl, QMouseEvent.Type.MouseButtonPress, self.tl.time_to_x(at(10)) + 30)  # 30 px ≈ 1.8 s: fuera del alcance
        self.assertEqual(len(self.seeks), 1)

    def test_coverage_is_merged_and_the_rest_is_a_gap(self) -> None:
        clips = {1: [Clip(1, at(0), at(20))], 2: [Clip(2, at(15), at(30))], 3: [Clip(3, at(45), at(60))]}
        self.tl.set_coverage(clips)
        self.assertEqual(self.tl._coverage, [(at(0), at(30)), (at(45), at(60))])

    def test_tick_step_grows_when_the_context_is_longer(self) -> None:
        short = self.tl._tick_step()
        self.tl.set_context(at(0), at(3600))
        self.assertGreater(self.tl._tick_step(), short)

    def test_it_paints_without_errors_in_every_state(self) -> None:
        self.tl.set_coverage({1: [Clip(1, at(0), at(30))]})
        self.tl.draw_playhead(at(20))
        self.assertFalse(self.tl.grab().isNull())
        self.tl.clear_export_range()
        self.assertFalse(self.tl.grab().isNull())
        empty = ClipTimeline()
        self.assertFalse(empty.grab().isNull())  # sin contexto: no revienta


class RangeLabelTests(unittest.TestCase):
    def width(self, text: str) -> float:
        return 7.0 * len(text)

    def positions(self, left: float, right: float, total: float = 1000.0):
        return label_positions(self.width, left, right, total, "08:16:20", "08:29:57", "13 min 37 s")

    def test_a_wide_band_shows_start_duration_and_end_in_that_order_inside_it(self) -> None:
        labels = self.positions(100, 900)
        self.assertEqual([text for text, _x in labels], ["08:16:20", "13 min 37 s", "08:29:57"])
        self.assertEqual(labels[0][1], 108)  # pegada al asa izquierda
        self.assertEqual(labels[2][1] + self.width("08:29:57"), 892)  # y la de fin al asa derecha
        self.assertEqual(labels[1][1] + self.width("13 min 37 s") / 2, 500)  # duración al centro

    def test_a_narrower_band_drops_the_duration_first(self) -> None:
        labels = self.positions(100, 290)
        self.assertEqual([text for text, _x in labels], ["08:16:20", "08:29:57"])

    def test_a_tiny_band_puts_each_time_outside_its_handle_without_leaving_the_widget(self) -> None:
        (start_text, start_x), (end_text, end_x) = self.positions(500, 520)
        self.assertLessEqual(start_x + self.width(start_text), 500)
        self.assertGreaterEqual(end_x, 520)
        (_t, start_x), (_t2, end_x) = self.positions(0, 10, total=200)
        self.assertGreaterEqual(start_x, 0)
        (_t, start_x), (_t2, end_x) = self.positions(190, 200, total=200)
        self.assertLessEqual(end_x + self.width("08:29:57"), 200)

    def test_the_labels_follow_the_handle_while_dragging(self) -> None:
        tl = ClipTimeline()
        tl.set_context(datetime(2026, 9, 19, 10, 0), datetime(2026, 9, 19, 10, 10))
        tl.set_export_range(datetime(2026, 9, 19, 10, 2), datetime(2026, 9, 19, 10, 5))
        self.assertEqual(tl.range_texts(), ("10:02:00", "10:05:00", "3 min 00 s"))
        tl._drag_range = (datetime(2026, 9, 19, 10, 1), datetime(2026, 9, 19, 10, 5))
        self.assertEqual(tl.range_texts(), ("10:01:00", "10:05:00", "4 min 00 s"))
        tl.clear_export_range()
        tl._drag_range = None
        self.assertIsNone(tl.range_texts())


if __name__ == "__main__":
    unittest.main()
