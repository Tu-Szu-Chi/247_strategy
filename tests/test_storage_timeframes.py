import unittest
from datetime import datetime
from tempfile import TemporaryDirectory

from qt_platform.domain import Bar
from qt_platform.storage.bar_store import SQLiteBarStore


class StorageTimeframesTest(unittest.TestCase):
    def test_1m_and_1d_are_stored_separately(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteBarStore(f"{temp_dir}/bars.db")
            minute_bar = Bar(datetime(2024, 1, 2, 8, 45), datetime(2024, 1, 2).date(), "TX", "202401", "day", 1, 2, 0.5, 1.5, 10, None, "test")
            daily_bar = Bar(datetime(2024, 1, 2, 0, 0), datetime(2024, 1, 2).date(), "TX", "202401", "day", 3, 4, 2, 3.5, 100, 50, "test")

            store.upsert_bars("1m", [minute_bar])
            store.upsert_bars("1d", [daily_bar])

            minute_rows = store.list_bars("1m", "TX", datetime(2024, 1, 2, 0, 0), datetime(2024, 1, 2, 23, 59))
            daily_rows = store.list_bars("1d", "TX", datetime(2024, 1, 2, 0, 0), datetime(2024, 1, 2, 23, 59))

        self.assertEqual(len(minute_rows), 1)
        self.assertEqual(len(daily_rows), 1)
        self.assertEqual(minute_rows[0].ts, datetime(2024, 1, 2, 8, 45))
        self.assertEqual(daily_rows[0].ts, datetime(2024, 1, 2, 0, 0))
