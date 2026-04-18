import unittest
from datetime import date, datetime
from tempfile import TemporaryDirectory

from qt_platform.domain import Bar
from qt_platform.history_sync import build_history_entries, sync_history_days
from qt_platform.storage.bar_store import SQLiteBarStore
from qt_platform.symbol_registry import SymbolRegistryEntry


class RecordingProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, date, str]] = []

    def supports_history(self, market: str, instrument_type: str, symbol: str, timeframe: str) -> bool:
        if market == "TAIFEX" and instrument_type == "future":
            return timeframe in {"1d", "1m"}
        if market == "TWSE" and instrument_type in {"stock", "index"}:
            return timeframe in {"1d", "1m"}
        return False

    def fetch_history(self, symbol, start_date, end_date, timeframe, session_scope):
        self.calls.append((symbol, start_date, timeframe))
        ts = datetime.combine(start_date, datetime.min.time())
        contract_month = "202401" if symbol == "MTX" else ""
        instrument_key = f"index:{symbol}" if symbol in {"TWII", "TWOTC"} else symbol
        return [
            Bar(
                ts=ts,
                trading_day=start_date,
                symbol=symbol,
                instrument_key=instrument_key,
                contract_month=contract_month,
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


class HistorySyncTest(unittest.TestCase):
    def test_build_history_entries_includes_builtins_and_registry_stocks_only(self) -> None:
        entries = build_history_entries(
            [
                SymbolRegistryEntry(symbol="2330", root_symbol="2330", market="TWSE", instrument_type="stock"),
                SymbolRegistryEntry(symbol="MTX", root_symbol="MTX", market="TAIFEX", instrument_type="future"),
                SymbolRegistryEntry(symbol="TXO", root_symbol="TXO", market="TAIFEX", instrument_type="option"),
            ]
        )

        keys = {(entry.symbol, entry.instrument_type) for entry in entries}
        self.assertEqual(
            keys,
            {
                ("2330", "stock"),
                ("MTX", "future"),
                ("TWII", "index"),
                ("TWOTC", "index"),
            },
        )

    def test_sync_history_days_logs_skips_and_synced_rows_per_symbol_day(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteBarStore(f"{temp_dir}/bars.db")
            store.upsert_bars(
                "1d",
                [
                    Bar(
                        ts=datetime(2024, 1, 1),
                        trading_day=date(2024, 1, 1),
                        symbol="2330",
                        instrument_key="2330",
                        contract_month="",
                        session="day",
                        open=1,
                        high=1,
                        low=1,
                        close=1,
                        volume=1,
                        open_interest=None,
                        source="seed",
                    )
                ],
            )
            provider = RecordingProvider()
            logs: list[dict] = []
            result = sync_history_days(
                store=store,
                provider=provider,
                entries=build_history_entries(
                    [SymbolRegistryEntry(symbol="2330", root_symbol="2330", market="TWSE", instrument_type="stock")]
                ),
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 1),
                timeframes=["1d"],
                progress_callback=logs.append,
            )

        self.assertEqual(result.total_candidates, 4)
        self.assertEqual(result.processed, 4)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(result.synced, 3)
        self.assertEqual(result.failed, 0)
        self.assertEqual({call[0] for call in provider.calls}, {"MTX", "TWII", "TWOTC"})
        skipped_log = next(item for item in logs if item["status"] == "history_day_skipped")
        self.assertEqual(skipped_log["symbol"], "2330")
        self.assertEqual(skipped_log["trading_day"], "2024-01-01")
        self.assertEqual(skipped_log["action"], "skipped")
        self.assertEqual(skipped_log["message"], "existing_trading_day")
        self.assertEqual(skipped_log["rows_upserted"], 0)
        self.assertEqual(skipped_log["total_candidates"], 4)
        self.assertEqual(skipped_log["processed"], 4)
        synced_symbols = {item["symbol"] for item in logs if item["status"] == "history_day_synced"}
        self.assertEqual(synced_symbols, {"MTX", "TWII", "TWOTC"})


if __name__ == "__main__":
    unittest.main()
