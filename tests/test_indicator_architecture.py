from __future__ import annotations

from datetime import datetime
import unittest

from qt_platform.indicators import DataManager, IndicatorRunner
from qt_platform.indicators.catalog import (
    MONITOR_INDICATOR_SERIES_NAMES,
    STATEFUL_MONITOR_SERIES_NAMES,
    requires_market_state,
)
from qt_platform.indicators.collection.force_score import ForceScoreIndicator
from qt_platform.indicators.collection.sma import SmaIndicator
from qt_platform.indicators.registry import IndicatorRegistry
from qt_platform.monitor.indicator_backend import INDICATOR_SERIES_NAMES


class DerivedIndicator:
    @property
    def name(self) -> str:
        return "derived_test"

    @property
    def dependencies(self) -> list[str]:
        return ["force_score", "sma_5"]

    def update(self, context):
        force_score = context.get_dependency("force_score") or 0
        sma = context.get_dependency("sma_5") or 0
        from qt_platform.indicators.base import IndicatorValue

        return IndicatorValue(value=force_score + sma, timestamp=context.ts)


class MockBar:
    def __init__(self, close: float, volume: float, up_ticks: float, down_ticks: float) -> None:
        self.close = close
        self.volume = volume
        self.up_ticks = up_ticks
        self.down_ticks = down_ticks
        self.ts = datetime.now()


class IndicatorArchitectureTest(unittest.TestCase):
    def test_indicator_registry_uses_runtime_indicator_name(self) -> None:
        self.assertIs(IndicatorRegistry.get("force_score"), ForceScoreIndicator)
        self.assertIs(IndicatorRegistry.get("sma_20"), SmaIndicator)
        self.assertIsNotNone(IndicatorRegistry.get("force_score"))

    def test_monitor_indicator_catalog_is_shared_with_backend(self) -> None:
        self.assertEqual(tuple(INDICATOR_SERIES_NAMES), MONITOR_INDICATOR_SERIES_NAMES)
        self.assertIn("trend_quality_score", MONITOR_INDICATOR_SERIES_NAMES)
        self.assertNotIn("trend_quality", MONITOR_INDICATOR_SERIES_NAMES)
        self.assertIn("structure_state", STATEFUL_MONITOR_SERIES_NAMES)
        self.assertFalse(requires_market_state(["pressure_index"]))
        self.assertTrue(requires_market_state(["adx_14"]))

    def test_runner_executes_dependencies_in_dag_order(self) -> None:
        data_manager = DataManager()
        runner = IndicatorRunner(data_manager)
        stream_key = "shioaji:bars_1m:MTX"
        stream = data_manager.get_stream(stream_key)

        for index in range(5):
            stream.append(MockBar(close=100 + index, volume=1000, up_ticks=10, down_ticks=5))

        pipeline = runner.add_pipeline(
            "test_1m",
            [
                {"indicator": ForceScoreIndicator(), "mapping": {"src": stream_key}},
                {"indicator": SmaIndicator(window=5), "mapping": {"src": stream_key}},
                {"indicator": DerivedIndicator(), "mapping": {}},
            ],
        )

        runner.update_all(datetime.now())

        snapshot = pipeline.get_snapshot()
        self.assertEqual(pipeline.execution_order, ["force_score", "sma_5", "derived_test"])
        self.assertEqual(snapshot["derived_test"], snapshot["force_score"] + snapshot["sma_5"])
