"""Huecos "sin grabación" de la línea de tiempo del día (ver la nota de 2026-09-25: cortes
normales del DVR entre archivos consecutivos se pintaban como huecos falsos). Correr desde v_2/:
.venv/bin/python -m unittest camera_viewer.tests.test_timeline_widget -v"""
from __future__ import annotations

import os
import unittest
from datetime import date, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from camera_viewer.clip import Clip  # noqa: E402
from camera_viewer.export_hours import GAP_TOLERANCE  # noqa: E402
from camera_viewer.timeline_widget import SECONDS_PER_DAY, TimelineWidget  # noqa: E402

DAY = date(2026, 9, 25)


def at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 9, 25, hour, minute, second)


class TimelineWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.tl = TimelineWidget()
        self.tl.set_day(DAY)

    def test_a_gap_smaller_than_the_tolerance_between_two_clips_does_not_count(self) -> None:
        # el corte típico de un DVR real entre dos archivos consecutivos: 1 s de separación
        self.tl.set_clips({1: [Clip(1, at(9), at(9, 5)), Clip(1, at(9, 5, 1), at(9, 10))]})
        self.assertEqual(self.tl._gap_seconds(), [(0, self.tl._seconds_since_midnight(at(9))), (self.tl._seconds_since_midnight(at(9, 10)), SECONDS_PER_DAY)])

    def test_a_gap_right_at_the_tolerance_boundary_does_not_count(self) -> None:
        gap = int(GAP_TOLERANCE)
        clips = {1: [Clip(1, at(9), at(9, 5)), Clip(1, at(9, 5, gap), at(9, 10))]}
        self.tl.set_clips(clips)
        covered = self.tl._covered_seconds()
        self.assertEqual(len(covered), 1)  # los dos clips quedaron fusionados en un solo tramo

    def test_a_gap_larger_than_the_tolerance_still_shows_as_a_real_gap(self) -> None:
        clips = {1: [Clip(1, at(9), at(9, 5)), Clip(1, at(9, 20), at(9, 25))]}
        self.tl.set_clips(clips)
        covered = self.tl._covered_seconds()
        self.assertEqual(len(covered), 2)  # 15 min de diferencia: sí es un hueco real
        gaps = self.tl._gap_seconds()
        self.assertIn((self.tl._seconds_since_midnight(at(9, 5)), self.tl._seconds_since_midnight(at(9, 20))), gaps)

    def test_recording_on_any_single_channel_counts_as_covered(self) -> None:
        # canal 1 graba 9:00-9:05, canal 2 graba 9:05:01-9:10 (el hueco de 1s entre AMBOS también se fusiona)
        clips = {1: [Clip(1, at(9), at(9, 5))], 2: [Clip(2, at(9, 5, 1), at(9, 10))]}
        self.tl.set_clips(clips)
        self.assertEqual(len(self.tl._covered_seconds()), 1)

    def test_no_clips_at_all_is_one_gap_covering_the_whole_day(self) -> None:
        self.tl.set_clips({1: [], 2: []})
        self.assertEqual(self.tl._gap_seconds(), [(0, SECONDS_PER_DAY)])
        self.assertEqual(self.tl._covered_seconds(), [])

    def test_full_day_coverage_has_no_gaps(self) -> None:
        self.tl.set_clips({1: [Clip(1, at(0), datetime(2026, 9, 26, 0, 0, 0))]})
        self.assertEqual(self.tl._gap_seconds(), [])


if __name__ == "__main__":
    unittest.main()
