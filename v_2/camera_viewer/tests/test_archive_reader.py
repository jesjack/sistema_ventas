"""Leer del archivo local en vez de pedirle al DVR (ver archive_reader.py y su enganche en
download_manager.RecordingDownloadManager.submit). Correr desde v_2/:
.venv/bin/python -m unittest camera_viewer.tests.test_archive_reader -v"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from camera_viewer import archive_index as idx
from camera_viewer import archive_reader as reader

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")

DAY = datetime(2026, 9, 18)


def at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return DAY.replace(hour=hour, minute=minute, second=second)


def segment(channel: int, start: datetime, end: datetime, path: str = "ch1/a.dav", compacted: bool = False) -> idx.Segment:
    return idx.Segment(id=1, channel=channel, start=start, end=end, path=path, bytes=1000, compacted=compacted)


class FindCoveringSegmentTests(unittest.TestCase):
    def test_a_range_fully_inside_one_segment_is_found(self) -> None:
        seg = segment(1, at(9), at(9, 5))
        self.assertIs(reader.find_covering_segment([seg], at(9, 1), at(9, 3)), seg)

    def test_a_range_matching_the_segment_exactly_is_found(self) -> None:
        seg = segment(1, at(9), at(9, 5))
        self.assertIs(reader.find_covering_segment([seg], at(9), at(9, 5)), seg)

    def test_a_range_that_starts_or_ends_outside_the_segment_is_not_covered(self) -> None:
        seg = segment(1, at(9), at(9, 5))
        self.assertIsNone(reader.find_covering_segment([seg], at(8, 59), at(9, 3)))
        self.assertIsNone(reader.find_covering_segment([seg], at(9, 1), at(9, 6)))

    def test_a_range_spanning_two_segments_is_not_covered_by_either(self) -> None:
        first = segment(1, at(9), at(9, 5), path="a")
        second = segment(1, at(9, 5), at(9, 10), path="b")
        self.assertIsNone(reader.find_covering_segment([first, second], at(9, 4), at(9, 6)))

    def test_picks_the_first_covering_segment_when_more_than_one_would_do(self) -> None:
        wide = segment(1, at(8), at(10), path="ancho")
        narrow = segment(1, at(9), at(9, 5), path="angosto")
        self.assertIs(reader.find_covering_segment([wide, narrow], at(9, 1), at(9, 2)), wide)

    def test_no_segments_means_no_coverage(self) -> None:
        self.assertIsNone(reader.find_covering_segment([], at(9), at(9, 1)))


class LookupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_no_index_yet_means_no_hit(self) -> None:
        self.assertIsNone(reader.lookup(self.tmp, 1, at(9), at(9, 1)))

    def test_a_covered_range_is_found_through_the_real_index(self) -> None:
        conn = idx.open_db(self.tmp / "index.sqlite3")
        idx.add_segment(conn, 1, at(9), at(9, 5), "ch1/a.dav", 1000)
        conn.close()
        found = reader.lookup(self.tmp, 1, at(9, 1), at(9, 3))
        self.assertIsNotNone(found)
        self.assertEqual(found.path, "ch1/a.dav")

    def test_an_uncovered_range_or_the_wrong_channel_is_a_miss(self) -> None:
        conn = idx.open_db(self.tmp / "index.sqlite3")
        idx.add_segment(conn, 1, at(9), at(9, 5), "ch1/a.dav", 1000)
        conn.close()
        self.assertIsNone(reader.lookup(self.tmp, 1, at(10), at(10, 1)))
        self.assertIsNone(reader.lookup(self.tmp, 2, at(9, 1), at(9, 3)))


@unittest.skipUnless(FFMPEG and FFPROBE, "hace falta ffmpeg/ffprobe")
class ExtractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.archive_dir = self.tmp / "archivo"
        (self.archive_dir / "ch1").mkdir(parents=True)
        self.source = self.archive_dir / "ch1" / "seg.dav"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=96x64:rate=10:duration=10",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "10", "-f", "mpegts", str(self.source)],
            check=True,
        )
        self.segment = segment(1, at(9), at(9, 0, 10), path="ch1/seg.dav")
        self.destination_dir = self.tmp / "descargas"

    def duration_of(self, path: Path) -> float:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, check=True,
        )
        return float(result.stdout.strip())

    def test_extracts_the_requested_slice_into_a_new_playable_file(self) -> None:
        result = reader.extract(self.archive_dir, self.segment, at(9, 0, 2), at(9, 0, 6), self.destination_dir)
        self.assertIsNotNone(result)
        self.assertTrue(result.exists())
        self.assertTrue(result.is_relative_to(self.destination_dir))
        self.assertAlmostEqual(self.duration_of(result), 4.0, delta=1.0)

    def test_a_missing_source_file_returns_none(self) -> None:
        self.source.unlink()
        self.assertIsNone(reader.extract(self.archive_dir, self.segment, at(9, 0, 2), at(9, 0, 6), self.destination_dir))
        self.assertEqual(list(self.destination_dir.glob("*")) if self.destination_dir.exists() else [], [])

    def test_without_ffmpeg_it_fails_cleanly(self) -> None:
        self.assertIsNone(
            reader.extract(self.archive_dir, self.segment, at(9, 0, 2), at(9, 0, 6), self.destination_dir, ffmpeg="/no/existe/ffmpeg")
        )

    def test_an_already_cancelled_stop_event_skips_the_work(self) -> None:
        stop = threading.Event()
        stop.set()
        self.assertIsNone(reader.extract(self.archive_dir, self.segment, at(9, 0, 2), at(9, 0, 6), self.destination_dir, stop_event=stop))
        self.assertEqual(list(self.destination_dir.glob("*")) if self.destination_dir.exists() else [], [])

    def test_each_call_gets_its_own_file_name(self) -> None:
        first = reader.extract(self.archive_dir, self.segment, at(9, 0, 2), at(9, 0, 4), self.destination_dir)
        second = reader.extract(self.archive_dir, self.segment, at(9, 0, 4), at(9, 0, 6), self.destination_dir)
        self.assertNotEqual(first, second)
        self.assertTrue(first.exists() and second.exists())


if __name__ == "__main__":
    unittest.main()
