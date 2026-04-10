import unittest
from datetime import date, datetime
from tempfile import TemporaryDirectory

from qt_platform.domain import Bar
from qt_platform.storage.bar_store import SQLiteBarStore
from qt_platform.symbol_registry import SymbolRegistryEntry
from qt_platform.sync_executor import sync_registry


class RecordingProvider:
    def __init__(self) -> None:
        self.batch_calls: list[tuple] = []
        self.single_calls: list[tuple] = []

    def supports_history(self, market: str, instrument_type: str, symbol: str, timeframe: str) -> bool:
        return market == "TAIFEX" and instrument_type == "future"

    def fetch_history(self, symbol, start_date, end_date, timeframe, session_scope):
        self.single_calls.append((symbol, start_date, end_date, timeframe, session_scope))
        if timeframe == "1m":
            return [
                Bar(
                    ts=datetime.combine(start_date, datetime.min.time()).replace(hour=8, minute=45),
                    trading_day=start_date,
                    symbol=symbol,
                    contract_month="202401",
                    session="day",
                    open=1,
                    high=1,
                    low=1,
                    close=1,
                    volume=1,
                    open_interest=None,
                    source="test",
                )
            ]
        return []

    def fetch_history_batch(self, market, symbols, start_date, end_date, timeframe, session_scope):
        self.batch_calls.append((market, tuple(symbols), start_date, end_date, timeframe, session_scope))
        payload = {}
        for symbol in symbols:
            payload[symbol] = [
                Bar(
                    ts=datetime.combine(start_date, datetime.min.time()),
                    trading_day=start_date,
                    symbol=symbol,
                    contract_month="202401",
                    session="day",
                    open=1,
                    high=1,
                    low=1,
                    close=1,
                    volume=1,
                    open_interest=None,
                    source="test",
                )
            ]
        return payload


class SyncExecutorTest(unittest.TestCase):
    def test_sync_registry_executes_bulk_daily_and_skips_unsupported_market(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteBarStore(f"{temp_dir}/bars.db")
            provider = RecordingProvider()
            result = sync_registry(
                store=store,
                provider=provider,
                entries=[
                    SymbolRegistryEntry(symbol="MTX", root_symbol="MTX", market="TAIFEX", instrument_type="future"),
                    SymbolRegistryEntry(symbol="2330", root_symbol="2330", market="TWSE", instrument_type="stock"),
                ],
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 2),
                timeframes=["1d", "1m"],
                requests_per_hour=6000,
                target_utilization=0.8,
            )

        self.assertEqual(len(provider.batch_calls), 1)
        self.assertEqual(provider.batch_calls[0][1], ("MTX",))
        actions = {(item.symbol, item.timeframe): item.action for item in result.items}
        self.assertEqual(actions[("MTX", "1d")], "synced")
        self.assertEqual(actions[("MTX", "1m")], "synced")
        self.assertEqual(actions[("2330", "1d")], "skipped_unsupported")
        self.assertEqual(actions[("2330", "1m")], "skipped_unsupported")

    def test_sync_registry_skips_repair_without_flag(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteBarStore(f"{temp_dir}/bars.db")
            store.upsert_bars(
                "1m",
                [
                    Bar(datetime(2024, 1, 1, 8, 45), date(2024, 1, 1), "MTX", "202401", "day", 1, 1, 1, 1, 1, None, "test"),
                    Bar(datetime(2024, 1, 3, 8, 45), date(2024, 1, 3), "MTX", "202401", "day", 1, 1, 1, 1, 1, None, "test"),
                ],
            )
            provider = RecordingProvider()
            result = sync_registry(
                store=store,
                provider=provider,
                entries=[SymbolRegistryEntry(symbol="MTX", root_symbol="MTX", market="TAIFEX", instrument_type="future")],
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 3),
                timeframes=["1m"],
                requests_per_hour=6000,
                target_utilization=0.8,
                allow_repair=False,
            )

        self.assertEqual(result.items[0].action, "skipped_repair")
        self.assertEqual(provider.single_calls, [])

    def test_sync_registry_executes_stock_and_option_daily_as_single_symbol_paths(self) -> None:
        class MultiAssetProvider(RecordingProvider):
            def supports_history(self, market: str, instrument_type: str, symbol: str, timeframe: str) -> bool:
                return timeframe == "1d" and (
                    (market == "TWSE" and instrument_type == "stock")
                    or (market == "TAIFEX" and instrument_type == "option" and symbol == "TXO")
                )

            def fetch_history(self, symbol, start_date, end_date, timeframe, session_scope):
                self.single_calls.append((symbol, start_date, end_date, timeframe, session_scope))
                return [
                    Bar(
                        ts=datetime.combine(start_date, datetime.min.time()),
                        trading_day=start_date,
                        symbol=symbol,
                        instrument_key=symbol,
                        contract_month="" if symbol == "2330" else "202401W1",
                        strike_price=18000.0 if symbol == "TXO" else None,
                        call_put="call" if symbol == "TXO" else None,
                        session="day",
                        open=1,
                        high=1,
                        low=1,
                        close=1,
                        volume=1,
                        open_interest=5 if symbol == "TXO" else None,
                        source="test",
                    )
                ]

        with TemporaryDirectory() as temp_dir:
            store = SQLiteBarStore(f"{temp_dir}/bars.db")
            provider = MultiAssetProvider()
            result = sync_registry(
                store=store,
                provider=provider,
                entries=[
                    SymbolRegistryEntry(symbol="2330", root_symbol="2330", market="TWSE", instrument_type="stock"),
                    SymbolRegistryEntry(symbol="TXO", root_symbol="TXO", market="TAIFEX", instrument_type="option"),
                ],
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 3),
                timeframes=["1d"],
                requests_per_hour=6000,
                target_utilization=0.8,
            )

        actions = {(item.symbol, item.timeframe): item.action for item in result.items}
        self.assertEqual(actions[("2330", "1d")], "synced")
        self.assertEqual(actions[("TXO", "1d")], "synced")
        self.assertEqual(len(provider.single_calls), 2)


if __name__ == "__main__":
    unittest.main()
