import unittest
from datetime import datetime, timedelta

from qt_platform.domain import Bar
from qt_platform.maintenance.service import MaintenanceService
from qt_platform.session import trading_day_for
from qt_platform.storage.bar_store import SQLiteBarStore


class DummyProvider:
    def supports_history(self, *args, **kwargs):
        return True

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
                    Bar(datetime(2024, 1, 1, 8, 45), datetime(2024, 1, 1).date(), "TX", "202401", "day", 1, 1, 1, 1, 1, None, "test"),
                    Bar(datetime(2024, 1, 1, 8, 47), datetime(2024, 1, 1).date(), "TX", "202401", "day", 1, 1, 1, 1, 1, None, "test"),
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

    def test_scan_gaps_ignores_non_trading_break_between_day_and_night_sessions(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temp_dir:
            store = SQLiteBarStore(f"{temp_dir}/bars.db")
            store.upsert_bars(
                "1m",
                [
                    Bar(datetime(2024, 1, 1, 13, 45), datetime(2024, 1, 1).date(), "MTX", "202401", "day", 1, 1, 1, 1, 1, None, "test"),
                    Bar(datetime(2024, 1, 1, 15, 0), datetime(2024, 1, 1).date(), "MTX", "202401", "night", 1, 1, 1, 1, 1, None, "test"),
                ],
            )
            service = MaintenanceService(provider=DummyProvider(), store=store)

            gaps = service.scan_gaps(
                symbol="MTX",
                start=datetime(2024, 1, 1, 13, 45),
                end=datetime(2024, 1, 1, 15, 0),
                expected_step=timedelta(minutes=1),
                session_scope="day_and_night",
            )

        self.assertEqual(gaps, [])

    def test_trading_day_for_after_midnight_night_session(self) -> None:
        self.assertEqual(
            trading_day_for(datetime(2024, 1, 2, 4, 30)),
            datetime(2024, 1, 1, 0, 0).date(),
        )

    def test_scan_gaps_handles_after_midnight_night_session_by_trading_day(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temp_dir:
            store = SQLiteBarStore(f"{temp_dir}/bars.db")
            store.upsert_bars(
                "1m",
                [
                    Bar(datetime(2024, 1, 1, 23, 58), datetime(2024, 1, 1).date(), "MTX", "202401", "night", 1, 1, 1, 1, 1, None, "test"),
                    Bar(datetime(2024, 1, 2, 0, 0), datetime(2024, 1, 1).date(), "MTX", "202401", "night", 1, 1, 1, 1, 1, None, "test"),
                ],
            )
            service = MaintenanceService(provider=DummyProvider(), store=store)

            gaps = service.scan_gaps(
                symbol="MTX",
                start=datetime(2024, 1, 1, 23, 58),
                end=datetime(2024, 1, 2, 0, 0),
                expected_step=timedelta(minutes=1),
                session_scope="night",
            )

        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].start, datetime(2024, 1, 1, 23, 59))
        self.assertEqual(gaps[0].end, datetime(2024, 1, 1, 23, 59))


if __name__ == "__main__":
    unittest.main()
