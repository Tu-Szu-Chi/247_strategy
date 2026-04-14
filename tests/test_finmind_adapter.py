import unittest
from datetime import datetime

from qt_platform.providers.finmind import FinMindAdapter
from qt_platform.settings import FinMindSettings


class FinMindAdapterTest(unittest.TestCase):
    def test_supports_history_only_taifex(self) -> None:
        adapter = FinMindAdapter(
            FinMindSettings(
                base_url="https://api.finmindtrade.com/api/v4",
                token_env="FINMIND_TOKEN",
                rps_limit=1,
                retry_limit=1,
                backoff_factor=2.0,
                timeout_seconds=30,
            )
        )

        self.assertTrue(adapter.supports_history(market="TAIFEX", instrument_type="future", symbol="MTX", timeframe="1d"))
        self.assertTrue(adapter.supports_history(market="TAIFEX", instrument_type="future", symbol="MTX", timeframe="1m"))
        self.assertTrue(adapter.supports_history(market="TWSE", instrument_type="stock", symbol="2330", timeframe="1d"))
        self.assertTrue(adapter.supports_history(market="TWSE", instrument_type="stock", symbol="2330", timeframe="1m"))
        self.assertTrue(adapter.supports_history(market="TAIFEX", instrument_type="option", symbol="TXO", timeframe="1d"))
        self.assertFalse(adapter.supports_history(market="TAIFEX", instrument_type="option", symbol="TXO", timeframe="1m"))

    def test_normalize_futures_row_maps_fields(self) -> None:
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

        bar = FinMindAdapter._normalize_futures_row(row, session_scope="day_and_night")

        self.assertEqual(bar.ts, datetime(2024, 4, 8, 0, 0, 0))
        self.assertEqual(bar.trading_day.isoformat(), "2024-04-08")
        self.assertEqual(bar.symbol, "TX")
        self.assertEqual(bar.instrument_key, "TX")
        self.assertEqual(bar.contract_month, "202404")
        self.assertEqual(bar.session, "day")
        self.assertEqual(bar.close, 20050.0)
        self.assertEqual(bar.open_interest, 98765.0)
        self.assertEqual(bar.build_source, "finmind_daily")

    def test_normalize_stock_row_maps_fields(self) -> None:
        row = {
            "date": "2024-04-08",
            "stock_id": "2330",
            "open": 800,
            "max": 820,
            "min": 790,
            "close": 815,
            "Trading_Volume": 123456,
        }

        bar = FinMindAdapter._normalize_stock_row(row)

        self.assertEqual(bar.symbol, "2330")
        self.assertEqual(bar.instrument_key, "2330")
        self.assertEqual(bar.contract_month, "")
        self.assertEqual(bar.session, "day")
        self.assertEqual(bar.volume, 123456.0)
        self.assertEqual(bar.build_source, "finmind_stock_daily")

    def test_normalize_option_row_maps_fields(self) -> None:
        row = {
            "date": "2024-04-08",
            "option_id": "TXO",
            "contract_date": "202404W1",
            "strike_price": 20000,
            "call_put": "call",
            "trading_session": "position",
            "open": 100,
            "max": 110,
            "min": 95,
            "close": 105,
            "volume": 321,
            "open_interest": 999,
        }

        bar = FinMindAdapter._normalize_option_row(row, session_scope="day_and_night")

        self.assertEqual(bar.symbol, "TXO")
        self.assertEqual(bar.contract_month, "202404W1")
        self.assertEqual(bar.strike_price, 20000.0)
        self.assertEqual(bar.call_put, "call")
        self.assertEqual(bar.open_interest, 999.0)
        self.assertEqual(bar.build_source, "finmind_option_daily")

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
        self.assertEqual(bars[0].trading_day.isoformat(), "2024-04-08")
        self.assertEqual(bars[0].open, 20000.0)
        self.assertEqual(bars[0].high, 20010.0)
        self.assertEqual(bars[0].low, 19990.0)
        self.assertEqual(bars[0].close, 19990.0)
        self.assertEqual(bars[0].volume, 6.0)
        self.assertEqual(bars[0].session, "day")
        self.assertEqual(bars[0].instrument_key, "TX")
        self.assertEqual(bars[0].build_source, "finmind_tick_agg")

    def test_fetch_daily_batch_calls_one_request_per_day(self) -> None:
        class StubFinMindAdapter(FinMindAdapter):
            def __init__(self):
                super().__init__(
                    FinMindSettings(
                        base_url="https://api.finmindtrade.com/api/v4",
                        token_env="FINMIND_TOKEN",
                        rps_limit=1,
                        retry_limit=1,
                        backoff_factor=2.0,
                        timeout_seconds=30,
                    )
                )
                self.calls = []

            def _get(self, api_version: str = "v4", **params: str) -> dict:
                self.calls.append((api_version, params))
                return {
                    "data": [
                        {
                            "date": params["start_date"],
                            "futures_id": "MTX",
                            "contract_date": "202401",
                            "trading_session": "position",
                            "open": 1,
                            "max": 1,
                            "min": 1,
                            "close": 1,
                            "volume": 1,
                            "open_interest": 1,
                        }
                    ]
                }

        adapter = StubFinMindAdapter()
        grouped = adapter._fetch_daily_batch(
            symbols=["MTX"],
            start_date=datetime(2024, 1, 1).date(),
            end_date=datetime(2024, 1, 3).date(),
            session_scope="day_and_night",
        )

        self.assertEqual(len(adapter.calls), 3)
        self.assertEqual(len(grouped["MTX"]), 3)

    def test_fetch_option_daily_uses_v4_single_day_windows(self) -> None:
        class StubFinMindAdapter(FinMindAdapter):
            def __init__(self):
                super().__init__(
                    FinMindSettings(
                        base_url="https://api.finmindtrade.com/api/v4",
                        token_env="FINMIND_TOKEN",
                        rps_limit=1,
                        retry_limit=1,
                        backoff_factor=2.0,
                        timeout_seconds=30,
                    )
                )
                self.calls = []

            def _get(self, api_version: str = "v4", **params: str) -> dict:
                self.calls.append((api_version, params))
                return {"data": []}

        adapter = StubFinMindAdapter()
        adapter._fetch_option_daily(
            symbol="TXO",
            start_date=datetime(2024, 1, 1).date(),
            end_date=datetime(2024, 1, 3).date(),
            session_scope="day_and_night",
        )

        self.assertEqual(
            adapter.calls,
            [
                ("v4", {"dataset": "TaiwanOptionDaily", "data_id": "TXO", "start_date": "2024-01-01", "end_date": "2024-01-01", "timeout_seconds": 120}),
                ("v4", {"dataset": "TaiwanOptionDaily", "data_id": "TXO", "start_date": "2024-01-02", "end_date": "2024-01-02", "timeout_seconds": 120}),
                ("v4", {"dataset": "TaiwanOptionDaily", "data_id": "TXO", "start_date": "2024-01-03", "end_date": "2024-01-03", "timeout_seconds": 120}),
            ],
        )

    def test_aggregate_stock_ticks_to_minute_bars(self) -> None:
        rows = [
            {
                "date": "2026-04-13",
                "Time": "09:00:06.761851",
                "stock_id": "2330",
                "deal_price": 1985,
                "volume": 2665,
                "TickType": 2,
            },
            {
                "date": "2026-04-13",
                "Time": "09:00:06.877284",
                "stock_id": "2330",
                "deal_price": 1990,
                "volume": 1,
                "TickType": 1,
            },
            {
                "date": "2026-04-13",
                "Time": "09:00:59.000000",
                "stock_id": "2330",
                "deal_price": 1988,
                "volume": 2,
                "TickType": 1,
            },
        ]

        bars = FinMindAdapter._aggregate_stock_ticks(rows, session_scope="day_and_night")

        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].ts, datetime(2026, 4, 13, 9, 0))
        self.assertEqual(bars[0].symbol, "2330")
        self.assertEqual(bars[0].open, 1985.0)
        self.assertEqual(bars[0].high, 1990.0)
        self.assertEqual(bars[0].low, 1985.0)
        self.assertEqual(bars[0].close, 1988.0)
        self.assertEqual(bars[0].volume, 2668.0)
        self.assertEqual(bars[0].up_ticks, 2)
        self.assertEqual(bars[0].down_ticks, 1)
        self.assertEqual(bars[0].build_source, "finmind_stock_tick_agg")

    def test_fetch_stock_minute_from_ticks_uses_single_day_requests(self) -> None:
        class StubFinMindAdapter(FinMindAdapter):
            def __init__(self):
                super().__init__(
                    FinMindSettings(
                        base_url="https://api.finmindtrade.com/api/v4",
                        token_env="FINMIND_TOKEN",
                        rps_limit=1,
                        retry_limit=1,
                        backoff_factor=2.0,
                        timeout_seconds=30,
                    )
                )
                self.calls = []

            def _get(self, api_version: str = "v4", **params: str) -> dict:
                self.calls.append((api_version, params))
                return {
                    "data": [
                        {
                            "date": params["start_date"],
                            "Time": "09:00:00.000000",
                            "stock_id": "2330",
                            "deal_price": 100,
                            "volume": 1,
                            "TickType": 1,
                        }
                    ]
                }

        adapter = StubFinMindAdapter()
        bars = adapter._fetch_stock_minute_from_ticks(
            symbol="2330",
            start_date=datetime(2024, 1, 1).date(),
            end_date=datetime(2024, 1, 3).date(),
            session_scope="day_and_night",
        )

        self.assertEqual(len(adapter.calls), 3)
        self.assertEqual(len(bars), 3)
        self.assertEqual(
            adapter.calls,
            [
                ("v4", {"dataset": "TaiwanStockPriceTick", "data_id": "2330", "start_date": "2024-01-01"}),
                ("v4", {"dataset": "TaiwanStockPriceTick", "data_id": "2330", "start_date": "2024-01-02"}),
                ("v4", {"dataset": "TaiwanStockPriceTick", "data_id": "2330", "start_date": "2024-01-03"}),
            ],
        )


if __name__ == "__main__":
    unittest.main()
