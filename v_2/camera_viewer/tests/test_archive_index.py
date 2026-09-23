"""Índice del archivo local de grabaciones. Correr desde v_2/:
.venv/bin/python -m unittest camera_viewer.tests.test_archive_index -v"""
from __future__ import annotations

import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from camera_viewer import archive_index as idx

DAY = datetime(2026, 9, 16)


def at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return DAY.replace(hour=hour, minute=minute, second=second)


class CursorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.conn = idx.open_db(self.tmp / "index.sqlite3")
        self.addCleanup(self.conn.close)

    def test_no_cursor_yet_is_none(self) -> None:
        self.assertIsNone(idx.get_cursor(self.conn, 1))

    def test_set_then_get_round_trips(self) -> None:
        idx.set_cursor(self.conn, 1, at(13, 30))
        self.assertEqual(idx.get_cursor(self.conn, 1), at(13, 30))

    def test_setting_again_overwrites_not_duplicates(self) -> None:
        idx.set_cursor(self.conn, 1, at(9))
        idx.set_cursor(self.conn, 1, at(15))
        self.assertEqual(idx.get_cursor(self.conn, 1), at(15))

    def test_cursors_are_independent_per_channel(self) -> None:
        idx.set_cursor(self.conn, 1, at(9))
        idx.set_cursor(self.conn, 2, at(12))
        self.assertEqual(idx.get_cursor(self.conn, 1), at(9))
        self.assertEqual(idx.get_cursor(self.conn, 2), at(12))

    def test_the_cursor_is_independent_from_what_segments_exist(self) -> None:
        """Un hueco real (sin grabación) avanza el cursor sin que haya ningún segmento."""
        idx.set_cursor(self.conn, 1, at(20))
        self.assertIsNone(idx.latest_end(self.conn, 1))
        self.assertEqual(idx.get_cursor(self.conn, 1), at(20))


class IndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.conn = idx.open_db(self.tmp / "index.sqlite3")
        self.addCleanup(self.conn.close)

    def add(self, channel: int, start: datetime, end: datetime, path: str, size: int = 1000, compacted: bool = False) -> int:
        return idx.add_segment(self.conn, channel, start, end, path, size, compacted)

    def test_the_db_file_and_schema_are_created(self) -> None:
        self.assertTrue((self.tmp / "index.sqlite3").exists())
        self.assertEqual(idx.channels(self.conn), [])
        self.assertIsNone(idx.oldest_segment(self.conn))
        self.assertEqual(idx.total_bytes(self.conn), 0)

    def test_opening_an_existing_db_again_does_not_lose_data(self) -> None:
        self.add(1, at(13), at(14), "1/a.dav", 500)
        self.conn.close()
        conn2 = idx.open_db(self.tmp / "index.sqlite3")
        self.addCleanup(conn2.close)
        self.assertEqual(len(idx.segments_for_channel(conn2, 1)), 1)

    def test_add_and_read_back_a_segment(self) -> None:
        segment_id = self.add(1, at(13), at(13, 5), "1/000.dav", 12345)
        segments = idx.segments_for_channel(self.conn, 1)
        self.assertEqual(len(segments), 1)
        segment = segments[0]
        self.assertEqual((segment.id, segment.channel, segment.start, segment.end), (segment_id, 1, at(13), at(13, 5)))
        self.assertEqual((segment.path, segment.bytes, segment.compacted), ("1/000.dav", 12345, False))
        self.assertAlmostEqual(segment.seconds, 300)

    def test_segments_for_a_channel_come_back_in_time_order_regardless_of_insertion_order(self) -> None:
        self.add(1, at(14), at(15), "1/b.dav")
        self.add(1, at(13), at(14), "1/a.dav")
        self.add(2, at(13), at(14), "2/a.dav")  # otro canal: no se mezcla
        segments = idx.segments_for_channel(self.conn, 1)
        self.assertEqual([s.path for s in segments], ["1/a.dav", "1/b.dav"])

    def test_latest_end_and_oldest_start_per_channel(self) -> None:
        self.assertIsNone(idx.latest_end(self.conn, 1))
        self.assertIsNone(idx.oldest_start(self.conn, 1))
        self.add(1, at(13), at(14), "1/a.dav")
        self.add(1, at(14), at(15), "1/b.dav")
        self.add(1, at(11), at(12), "1/z.dav")  # más vieja, insertada al final
        self.assertEqual(idx.latest_end(self.conn, 1), at(15))
        self.assertEqual(idx.oldest_start(self.conn, 1), at(11))

    def test_segments_covering_a_range_only_returns_overlaps(self) -> None:
        self.add(1, at(9), at(10), "1/a.dav")
        self.add(1, at(10), at(11), "1/b.dav")
        self.add(1, at(12), at(13), "1/c.dav")
        covering = idx.segments_covering(self.conn, 1, at(9, 30), at(10, 30))
        self.assertEqual([s.path for s in covering], ["1/a.dav", "1/b.dav"])
        self.assertEqual(idx.segments_covering(self.conn, 1, at(11), at(12)), [])  # el hueco entre b y c
        self.assertEqual(idx.segments_covering(self.conn, 1, at(20), at(21)), [])
        self.assertEqual(idx.segments_covering(self.conn, 2, at(9), at(10)), [])  # otro canal

    def test_oldest_segment_is_global_across_channels(self) -> None:
        self.add(2, at(12), at(13), "2/a.dav")
        self.add(1, at(9), at(10), "1/a.dav")  # la más vieja de todas
        self.add(1, at(20), at(21), "1/b.dav")
        oldest = idx.oldest_segment(self.conn)
        self.assertEqual(oldest.path, "1/a.dav")

    def test_total_bytes_sums_every_segment(self) -> None:
        self.add(1, at(9), at(10), "1/a.dav", 1000)
        self.add(2, at(9), at(10), "2/a.dav", 2500)
        self.assertEqual(idx.total_bytes(self.conn), 3500)

    def test_channels_lists_only_the_ones_with_segments(self) -> None:
        self.add(3, at(9), at(10), "3/a.dav")
        self.add(1, at(9), at(10), "1/a.dav")
        self.assertEqual(idx.channels(self.conn), [1, 3])

    def test_mark_compacted_replaces_path_and_size_and_flags_it(self) -> None:
        segment_id = self.add(1, at(9), at(10), "1/raw.dav", 20_000_000, compacted=False)
        idx.mark_compacted(self.conn, segment_id, "1/comp.mp4", 2_000_000)
        segment = idx.get_segment(self.conn, segment_id)
        self.assertEqual((segment.path, segment.bytes, segment.compacted), ("1/comp.mp4", 2_000_000, True))
        self.assertEqual(segment.start, at(9))  # el rango de tiempo no cambia al compactar

    def test_delete_segment_only_touches_the_index(self) -> None:
        segment_id = self.add(1, at(9), at(10), "1/a.dav")
        idx.delete_segment(self.conn, segment_id)
        self.assertIsNone(idx.get_segment(self.conn, segment_id))
        self.assertEqual(idx.segments_for_channel(self.conn, 1), [])

    def test_pending_compaction_lists_only_raw_segments_oldest_first(self) -> None:
        self.add(1, at(14), at(15), "1/raw_b.dav", compacted=False)
        self.add(1, at(9), at(10), "1/raw_a.dav", compacted=False)
        self.add(1, at(11), at(12), "1/done.mp4", compacted=True)
        pending = idx.pending_compaction(self.conn)
        self.assertEqual([s.path for s in pending], ["1/raw_a.dav", "1/raw_b.dav"])

    def test_pending_compaction_respects_the_limit(self) -> None:
        for hour in range(9, 15):
            self.add(1, at(hour), at(hour + 1), f"1/{hour}.dav")
        self.assertEqual(len(idx.pending_compaction(self.conn, limit=2)), 2)

    def test_a_duplicate_path_is_rejected(self) -> None:
        self.add(1, at(9), at(10), "1/a.dav")
        with self.assertRaises(Exception):
            self.add(1, at(10), at(11), "1/a.dav")

    def test_a_writer_and_a_reader_from_separate_connections_do_not_deadlock(self) -> None:
        """WAL: un lector no debe esperar a un escritor que aún no terminó su transacción."""
        writer = idx.open_db(self.tmp / "index.sqlite3")
        self.addCleanup(writer.close)
        idx.add_segment(writer, 1, at(9), at(10), "1/a.dav", 1000)
        # Otra conexión (como si fuera otro proceso) lee sin abrir una transacción larga de por medio.
        reader = idx.open_db(self.tmp / "index.sqlite3")
        self.addCleanup(reader.close)
        self.assertEqual(len(idx.segments_for_channel(reader, 1)), 1)

    def test_concurrent_writers_from_different_threads_do_not_corrupt_the_index(self) -> None:
        errors = []

        def worker(channel: int) -> None:
            try:
                conn = idx.open_db(self.tmp / "index.sqlite3")
                for hour in range(9, 9 + 5):
                    idx.add_segment(conn, channel, at(hour), at(hour + 1), f"{channel}/{hour}.dav", 1000)
                conn.close()
            except Exception as exc:  # pragma: no cover - solo si algo se corrompe de verdad
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(channel,)) for channel in (1, 2, 3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertEqual(errors, [])
        conn = idx.open_db(self.tmp / "index.sqlite3")
        self.addCleanup(conn.close)
        self.assertEqual(idx.total_bytes(conn), 15 * 1000)


if __name__ == "__main__":
    unittest.main()
