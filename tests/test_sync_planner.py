import unittest
from datetime import datetime
from tempfile import TemporaryDirectory

from qt_platform.domain import Bar
from qt_platform.storage.bar_store import SQLiteBarStore
from qt_platform.symbol_registry import SymbolRegistryEntry
from qt_platform.sync_planner import plan_sync


class SyncPlannerTest(unittest.TestCase):
    def test_plan_sync_bootstrap_and_bulk_daily_estimation(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteBarStore(f"{temp_dir}/bars.db")
            plan = plan_sync(
                store=store,
                entries=[
                    SymbolRegistryEntry(symbol="MTX", root_symbol="MTX", market="TAIFEX", instrument_type="future"),
                    SymbolRegistryEntry(symbol="TX", root_symbol="TX", market="TAIFEX", instrument_type="future"),
                ],
                start_date=datetime(2024, 1, 1).date(),
                end_date=datetime(2024, 1, 3).date(),
                timeframes=["1d", "1m"],
                requests_per_hour=6000,
                target_utilization=0.8,
            )

        self.assertEqual(plan.timeframe_totals["1d"]["estimated_requests"], 3)
        self.assertEqual(plan.timeframe_totals["1m"]["estimated_requests"], 6)
        self.assertEqual(plan.total_estimated_requests, 9)
        self.assertEqual(plan.items[0].mode, "bootstrap")

    def test_plan_sync_detects_catch_up_and_repair(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteBarStore(f"{temp_dir}/bars.db")
            store.upsert_bars(
                "1m",
                [
                    Bar(datetime(2024, 1, 1, 8, 45), datetime(2024, 1, 1).date(), "MTX", "202401", "day", 1, 1, 1, 1, 1, None, "test"),
                    Bar(datetime(2024, 1, 2, 8, 45), datetime(2024, 1, 2).date(), "MTX", "202401", "day", 1, 1, 1, 1, 1, None, "test"),
                ],
            )
            catch_up_plan = plan_sync(
                store=store,
                entries=[SymbolRegistryEntry(symbol="MTX", root_symbol="MTX", market="TAIFEX", instrument_type="future")],
                start_date=datetime(2024, 1, 3).date(),
                end_date=datetime(2024, 1, 4).date(),
                timeframes=["1m"],
                requests_per_hour=6000,
                target_utilization=0.8,
            )
            store.upsert_bars(
                "1m",
                [
                    Bar(datetime(2024, 1, 3, 8, 45), datetime(2024, 1, 3).date(), "MTX", "202401", "day", 1, 1, 1, 1, 1, None, "test"),
                    Bar(datetime(2024, 1, 1, 8, 45), datetime(2024, 1, 1).date(), "TX", "202401", "day", 1, 1, 1, 1, 1, None, "test"),
                    Bar(datetime(2024, 1, 3, 8, 45), datetime(2024, 1, 3).date(), "TX", "202401", "day", 1, 1, 1, 1, 1, None, "test"),
                ],
            )
            repair_plan = plan_sync(
                store=store,
                entries=[SymbolRegistryEntry(symbol="TX", root_symbol="TX", market="TAIFEX", instrument_type="future")],
                start_date=datetime(2024, 1, 1).date(),
                end_date=datetime(2024, 1, 3).date(),
                timeframes=["1m"],
                requests_per_hour=6000,
                target_utilization=0.8,
            )

        self.assertEqual(catch_up_plan.items[0].mode, "catch_up")
        self.assertEqual(catch_up_plan.items[0].estimated_requests, 2)
        self.assertEqual(repair_plan.items[0].mode, "repair")
        self.assertEqual([value.isoformat() for value in repair_plan.items[0].missing_dates], ["2024-01-02"])

    def test_plan_sync_estimates_stock_and_option_daily_differently(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteBarStore(f"{temp_dir}/bars.db")
            plan = plan_sync(
                store=store,
                entries=[
                    SymbolRegistryEntry(symbol="2330", root_symbol="2330", market="TWSE", instrument_type="stock"),
                    SymbolRegistryEntry(symbol="TXO", root_symbol="TXO", market="TAIFEX", instrument_type="option"),
                ],
                start_date=datetime(2024, 1, 1).date(),
                end_date=datetime(2024, 1, 3).date(),
                timeframes=["1d"],
                requests_per_hour=6000,
                target_utilization=0.8,
            )

        items = {(item.symbol, item.timeframe): item for item in plan.items}
        self.assertEqual(items[("2330", "1d")].request_strategy, "per_symbol_range")
        self.assertEqual(items[("2330", "1d")].estimated_requests, 1)
        self.assertEqual(items[("TXO", "1d")].request_strategy, "per_symbol_per_day_chain")
        self.assertEqual(items[("TXO", "1d")].estimated_requests, 3)
        self.assertEqual(plan.timeframe_totals["1d"]["estimated_requests"], 4)

    def test_plan_sync_to_dict_serializes_nested_dates(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteBarStore(f"{temp_dir}/bars.db")
            plan = plan_sync(
                store=store,
                entries=[SymbolRegistryEntry(symbol="MTX", root_symbol="MTX", market="TAIFEX", instrument_type="future")],
                start_date=datetime(2024, 1, 1).date(),
                end_date=datetime(2024, 1, 2).date(),
                timeframes=["1d"],
                requests_per_hour=6000,
                target_utilization=0.8,
            )

        payload = plan.to_dict()
        request_dates = payload["timeframe_totals"]["1d"]["strategy_breakdown"]["bulk_daily_all_symbols"]["request_dates"]
        self.assertEqual(request_dates, ["2024-01-01", "2024-01-02"])


if __name__ == "__main__":
    unittest.main()
