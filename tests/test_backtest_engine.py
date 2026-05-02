import unittest
from datetime import datetime, timedelta

from qt_platform.backtest.engine import BacktestConfig, indicator_series_to_context_extras, run_backtest
from qt_platform.domain import Bar, Side, Signal
from qt_platform.strategies.base import (
    BarCloseEvent,
    BaseIndicator,
    BaseSignalLogic,
    BaseStrategy,
    BaseStrategyDefinition,
    FixedSizeExecutionPolicy,
    IndicatorValue,
    PortfolioState,
    SignalAction,
    SignalDecisionContext,
    SignalIntent,
    StrategyUniverse,
    StrategyContext,
)
from qt_platform.strategies.sma_cross import SmaCrossStrategy


class OneShotStrategy(BaseStrategy):
    def __init__(self) -> None:
        self.emitted = False

    def on_bar(self, context: StrategyContext):
        if self.emitted:
            return []
        self.emitted = True
        return [Signal(ts=context.bar.ts, side=Side.BUY, size=1, reason="entry")]


class BacktestEngineTest(unittest.TestCase):
    def test_signal_fills_on_next_open(self) -> None:
        start = datetime(2024, 1, 1, 8, 45)
        bars = [
            Bar(start, start.date(), "MTX", "202401", "day", 100, 101, 99, 100, 10, None, "test"),
            Bar(start + timedelta(minutes=1), start.date(), "MTX", "202401", "day", 105, 106, 104, 105, 10, None, "test"),
        ]

        result = run_backtest(bars=bars, strategy=OneShotStrategy(), config=BacktestConfig(starting_cash=1000))

        self.assertEqual(len(result.fills), 1)
        self.assertEqual(result.fills[0].ts, start + timedelta(minutes=1))
        self.assertEqual(result.fills[0].price, 105)

    def test_signal_metadata_is_preserved_on_fill(self) -> None:
        class MetadataStrategy(BaseStrategy):
            def on_bar(self, context: StrategyContext):
                if context.bar_index != 0:
                    return []
                return [
                    Signal(
                        ts=context.bar.ts,
                        side=Side.BUY,
                        size=1,
                        reason="entry",
                        metadata={"flow_state": 1, "pressure_index": 62.5},
                    )
                ]

        start = datetime(2024, 1, 1, 8, 45)
        bars = [
            Bar(start, start.date(), "MTX", "202401", "day", 100, 101, 99, 100, 10, None, "test"),
            Bar(start + timedelta(minutes=1), start.date(), "MTX", "202401", "day", 105, 106, 104, 105, 10, None, "test"),
        ]

        result = run_backtest(bars=bars, strategy=MetadataStrategy(), config=BacktestConfig(starting_cash=1000))

        self.assertEqual(result.fills[0].metadata, {"flow_state": 1, "pressure_index": 62.5})

    def test_strategy_definition_runs_indicator_signal_and_execution_layers(self) -> None:
        class ThresholdIndicator(BaseIndicator):
            def __init__(self) -> None:
                self.last_close = None

            def on_bar(self, event: BarCloseEvent) -> None:
                self.last_close = event.bar.close

            def snapshot(self) -> IndicatorValue:
                return IndicatorValue(value=self.last_close, ready=self.last_close is not None)

        class ThresholdSignalLogic(BaseSignalLogic):
            def evaluate(self, context: SignalDecisionContext, indicator_values: dict[str, IndicatorValue]):
                close_value = indicator_values["close"]
                if not close_value.ready or close_value.value < 105:
                    return []
                return [
                    SignalIntent(
                        ts=context.event.bar.ts,
                        symbol=context.event.bar.symbol,
                        action=SignalAction.BUY,
                        strength=0.8,
                        reason="close_ge_105",
                    )
                ]

        class ThresholdStrategy(BaseStrategyDefinition):
            def __init__(self) -> None:
                self._indicators = {"close": ThresholdIndicator()}
                self._signal_logic = ThresholdSignalLogic()
                self._execution_policy = FixedSizeExecutionPolicy(trade_size=1, max_position=1)

            def indicators(self):
                return self._indicators

            def signal_logic(self):
                return self._signal_logic

            def execution_policy(self):
                return self._execution_policy

        start = datetime(2024, 1, 1, 8, 45)
        bars = [
            Bar(start, start.date(), "MTX", "202401", "day", 100, 101, 99, 100, 10, None, "test"),
            Bar(start + timedelta(minutes=1), start.date(), "MTX", "202401", "day", 106, 107, 105, 106, 10, None, "test"),
            Bar(start + timedelta(minutes=2), start.date(), "MTX", "202401", "day", 107, 108, 106, 107, 10, None, "test"),
        ]

        result = run_backtest(bars=bars, strategy=ThresholdStrategy(), config=BacktestConfig(starting_cash=1000))

        self.assertEqual(len(result.fills), 1)
        self.assertEqual(result.fills[0].ts, start + timedelta(minutes=2))
        self.assertEqual(result.fills[0].price, 107)

    def test_fixed_execution_policy_respects_max_position(self) -> None:
        policy = FixedSizeExecutionPolicy(trade_size=1, max_position=1)
        context = SignalDecisionContext(
            event=BarCloseEvent(
                bar=Bar(
                    datetime(2024, 1, 1, 8, 45),
                    datetime(2024, 1, 1).date(),
                    "MTX",
                    "202401",
                    "day",
                    100,
                    101,
                    99,
                    100,
                    10,
                    None,
                    "test",
                )
            ),
            portfolio=PortfolioState(cash=1000.0, position_size=1, average_entry_price=100.0),
            universe=StrategyUniverse(primary_symbol="MTX"),
        )
        decisions = policy.decide(
            [
                SignalIntent(
                    ts=datetime(2024, 1, 1, 8, 45),
                    symbol="MTX",
                    action=SignalAction.BUY,
                    reason="duplicate_buy",
                )
            ],
            context,
        )
        self.assertEqual(decisions, [])

    def test_sma_cross_strategy_uses_new_strategy_definition_path(self) -> None:
        start = datetime(2024, 1, 1, 8, 45)
        closes = [10, 10, 10, 10, 10, 20, 20, 20]
        bars = [
            Bar(
                start + timedelta(minutes=index),
                start.date(),
                "MTX",
                "202401",
                "day",
                close,
                close,
                close,
                close,
                10,
                None,
                "test",
            )
            for index, close in enumerate(closes)
        ]

        result = run_backtest(
            bars=bars,
            strategy=SmaCrossStrategy(fast_window=3, slow_window=5),
            config=BacktestConfig(starting_cash=1000),
        )

        self.assertEqual(len(result.fills), 1)
        self.assertEqual(result.fills[0].side, Side.BUY)
        self.assertEqual(result.fills[0].ts, start + timedelta(minutes=6))

    def test_same_bar_execution_uses_target_price(self) -> None:
        class StopStrategy(BaseStrategy):
            def on_bar(self, context: StrategyContext):
                if context.bar_index == 0:
                    return [Signal(ts=context.bar.ts, side=Side.BUY, reason="entry")]
                return [
                    Signal(
                        ts=context.bar.ts,
                        side=Side.SELL,
                        size=max(context.position_size, 1),
                        reason="stop",
                        execution_mode="same_bar",
                        target_price=95.0,
                    )
                ]

        start = datetime(2024, 1, 1, 8, 45)
        bars = [
            Bar(start, start.date(), "MTX", "202401", "day", 100, 101, 99, 100, 10, None, "test", up_ticks=10, down_ticks=1),
            Bar(start + timedelta(minutes=1), start.date(), "MTX", "202401", "day", 105, 106, 90, 95, 10, None, "test", up_ticks=1, down_ticks=10),
        ]
        result = run_backtest(bars=bars, strategy=StopStrategy(), config=BacktestConfig(starting_cash=1000))
        self.assertEqual(len(result.fills), 2)
        self.assertEqual(result.fills[1].price, 95.0)
        self.assertEqual(result.fills[1].metadata, {})

    def test_indicator_series_are_available_as_strategy_context_extras(self) -> None:
        class FlowStateStrategy(BaseStrategy):
            def on_bar(self, context: StrategyContext):
                if context.extras.get("flow_state") != 1:
                    return []
                return [Signal(ts=context.bar.ts, side=Side.BUY, size=1, reason="backend_signal")]

        start = datetime(2024, 1, 1, 8, 45)
        bars = [
            Bar(start, start.date(), "MTX", "202401", "day", 100, 101, 99, 100, 10, None, "test"),
            Bar(start + timedelta(minutes=1), start.date(), "MTX", "202401", "day", 105, 106, 104, 105, 10, None, "test"),
        ]
        result = run_backtest(
            bars=bars,
            strategy=FlowStateStrategy(),
            config=BacktestConfig(starting_cash=1000),
            indicator_series={
                "flow_state": [{"time": start.isoformat(), "value": 1}],
            },
        )

        self.assertEqual(len(result.fills), 1)
        self.assertEqual(result.fills[0].ts, start + timedelta(minutes=1))
        self.assertEqual(result.fills[0].reason, "backend_signal")

    def test_indicator_series_context_extras_can_be_overridden_by_explicit_extras(self) -> None:
        start = datetime(2024, 1, 1, 8, 45)

        extras = indicator_series_to_context_extras(
            {"flow_state": [{"time": start.isoformat(), "value": 1}]}
        )

        self.assertEqual(extras, {start: {"flow_state": 1}})

        class CaptureStrategy(BaseStrategy):
            def __init__(self) -> None:
                self.values = []

            def on_bar(self, context: StrategyContext):
                self.values.append(context.extras.get("flow_state"))
                return []

        strategy = CaptureStrategy()
        run_backtest(
            bars=[Bar(start, start.date(), "MTX", "202401", "day", 100, 101, 99, 100, 10, None, "test")],
            strategy=strategy,
            config=BacktestConfig(starting_cash=1000),
            context_extras_by_ts={start: {"flow_state": -1}},
            indicator_series={"flow_state": [{"time": start.isoformat(), "value": 1}]},
        )

        self.assertEqual(strategy.values, [-1])


if __name__ == "__main__":
    unittest.main()
