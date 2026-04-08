import unittest
from datetime import datetime

from qt_platform.providers.finmind import FinMindAdapter


class FinMindAdapterTest(unittest.TestCase):
    def test_normalize_row_maps_fields(self) -> None:
        row = {
            "date": "2024-04-08",
            "futures_id": "TX",
            "contract_date": "202404",
            "trading_session": "position",
            "open": 20000,
            "max": 20100,
            "min": 19950,
            "close": 20050,
            "volume": 12345,
            "open_interest": 98765,
        }

        bar = FinMindAdapter._normalize_row(row, session_scope="day_and_night")

        self.assertEqual(bar.ts, datetime(2024, 4, 8, 0, 0, 0))
        self.assertEqual(bar.symbol, "TX")
        self.assertEqual(bar.contract_month, "202404")
        self.assertEqual(bar.session, "day")
        self.assertEqual(bar.close, 20050.0)
        self.assertEqual(bar.open_interest, 98765.0)

    def test_aggregate_ticks_to_minute_bars(self) -> None:
        rows = [
            {
                "contract_date": "202404",
                "date": "2024-04-08 08:45:01",
                "futures_id": "TX",
                "price": 20000,
                "volume": 1,
            },
            {
                "contract_date": "202404",
                "date": "2024-04-08 08:45:30",
                "futures_id": "TX",
                "price": 20010,
                "volume": 2,
            },
            {
                "contract_date": "202404",
                "date": "2024-04-08 08:45:40",
                "futures_id": "TX",
                "price": 19990,
                "volume": 3,
            },
        ]

        bars = FinMindAdapter._aggregate_ticks(rows, session_scope="day_and_night")

        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].ts, datetime(2024, 4, 8, 8, 45))
        self.assertEqual(bars[0].open, 20000.0)
        self.assertEqual(bars[0].high, 20010.0)
        self.assertEqual(bars[0].low, 19990.0)
        self.assertEqual(bars[0].close, 19990.0)
        self.assertEqual(bars[0].volume, 6.0)
        self.assertEqual(bars[0].session, "day")


if __name__ == "__main__":
    unittest.main()
