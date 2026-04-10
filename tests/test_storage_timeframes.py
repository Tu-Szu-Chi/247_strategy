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

    def test_option_daily_rows_do_not_overwrite_each_other(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteBarStore(f"{temp_dir}/bars.db")
            bars = [
                Bar(
                    ts=datetime(2024, 4, 8, 0, 0),
                    trading_day=datetime(2024, 4, 8).date(),
                    symbol="TXO",
                    instrument_key="TXO:202404W1:18000:call",
                    contract_month="202404W1",
                    strike_price=18000.0,
                    call_put="call",
                    session="day",
                    open=10,
                    high=11,
                    low=9,
                    close=10.5,
                    volume=100,
                    open_interest=500,
                    source="test",
                ),
                Bar(
                    ts=datetime(2024, 4, 8, 0, 0),
                    trading_day=datetime(2024, 4, 8).date(),
                    symbol="TXO",
                    instrument_key="TXO:202404W1:18100:put",
                    contract_month="202404W1",
                    strike_price=18100.0,
                    call_put="put",
                    session="day",
                    open=12,
                    high=13,
                    low=11,
                    close=12.5,
                    volume=200,
                    open_interest=600,
                    source="test",
                ),
            ]

            store.upsert_bars("1d", bars)
            rows = store.list_bars("1d", "TXO", datetime(2024, 4, 8, 0, 0), datetime(2024, 4, 8, 23, 59))

        self.assertEqual(len(rows), 2)
        self.assertEqual({row.instrument_key for row in rows}, {"TXO:202404W1:18000:call", "TXO:202404W1:18100:put"})
