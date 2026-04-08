import unittest
from datetime import datetime, timedelta

from qt_platform.domain import Bar
from qt_platform.maintenance.service import MaintenanceService
from qt_platform.storage.bar_store import SQLiteBarStore


class DummyProvider:
    def fetch_history(self, *args, **kwargs):
        return []


class MaintenanceServiceTest(unittest.TestCase):
    def test_scan_gaps_detects_missing_window(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temp_dir:
            store = SQLiteBarStore(f"{temp_dir}/bars.db")
            store.upsert_bars(
                "1m",
                [
                    Bar(datetime(2024, 1, 1, 8, 45), "TX", "202401", "day", 1, 1, 1, 1, 1, None, "test"),
                    Bar(datetime(2024, 1, 1, 8, 47), "TX", "202401", "day", 1, 1, 1, 1, 1, None, "test"),
                ]
            )
            service = MaintenanceService(provider=DummyProvider(), store=store)

            gaps = service.scan_gaps(
                symbol="TX",
                start=datetime(2024, 1, 1, 8, 45),
                end=datetime(2024, 1, 1, 8, 47),
                expected_step=timedelta(minutes=1),
            )

        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].start, datetime(2024, 1, 1, 8, 46))
        self.assertEqual(gaps[0].end, datetime(2024, 1, 1, 8, 46))


if __name__ == "__main__":
    unittest.main()
