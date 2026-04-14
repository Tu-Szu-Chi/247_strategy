import unittest
from datetime import datetime, timedelta

from qt_platform.backtest.engine import BacktestConfig, run_backtest
from qt_platform.domain import Bar, Side, Signal
from qt_platform.strategies.base import BaseStrategy, StrategyContext
from qt_platform.strategies.force_imbalance import ForceImbalanceStrategy
from qt_platform.strategies.mxf_2330_pulse import Mxf2330PulseStrategy


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
            Bar(start, start.date(), "TX", "202401", "day", 100, 101, 99, 100, 10, None, "test"),
            Bar(start + timedelta(minutes=1), start.date(), "TX", "202401", "day", 105, 106, 104, 105, 10, None, "test"),
        ]

        result = run_backtest(bars=bars, strategy=OneShotStrategy(), config=BacktestConfig(starting_cash=1000))

        self.assertEqual(len(result.fills), 1)
        self.assertEqual(result.fills[0].ts, start + timedelta(minutes=1))
        self.assertEqual(result.fills[0].price, 105)

    def test_force_imbalance_strategy_uses_minute_features(self) -> None:
        start = datetime(2024, 1, 1, 8, 45)
        bars = [
            Bar(start, start.date(), "TX", "202401", "day", 100, 101, 99, 100, 1000, None, "test", up_ticks=80, down_ticks=20),
            Bar(start + timedelta(minutes=1), start.date(), "TX", "202401", "day", 105, 106, 104, 105, 1000, None, "test", up_ticks=20, down_ticks=80),
            Bar(start + timedelta(minutes=2), start.date(), "TX", "202401", "day", 103, 104, 102, 103, 1000, None, "test", up_ticks=50, down_ticks=50),
        ]

        strategy = ForceImbalanceStrategy(min_force_score=500, min_tick_bias_ratio=0.5)
        result = run_backtest(bars=bars, strategy=strategy, config=BacktestConfig(starting_cash=1000))

        self.assertEqual(len(result.fills), 2)
        self.assertEqual(result.fills[0].ts, start + timedelta(minutes=1))
        self.assertEqual(result.fills[0].side, Side.BUY)
        self.assertEqual(result.fills[1].ts, start + timedelta(minutes=2))
        self.assertEqual(result.fills[1].side, Side.SELL)

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
            Bar(start, start.date(), "TX", "202401", "day", 100, 101, 99, 100, 10, None, "test", up_ticks=10, down_ticks=1),
            Bar(start + timedelta(minutes=1), start.date(), "TX", "202401", "day", 105, 106, 90, 95, 10, None, "test", up_ticks=1, down_ticks=10),
        ]
        result = run_backtest(bars=bars, strategy=StopStrategy(), config=BacktestConfig(starting_cash=1000))
        self.assertEqual(len(result.fills), 2)
        self.assertEqual(result.fills[1].price, 95.0)

    def test_mxf_2330_pulse_strategy_respects_max_position_time_exit_and_stop(self) -> None:
        strategy = Mxf2330PulseStrategy(
            growth_threshold=0.3,
            max_position=2,
            stop_loss_points=100.0,
            force_exit_time="13:30",
        )
        start = datetime(2024, 1, 1, 9, 4)
        bars = [
            Bar(start, start.date(), "MXF1", "202401", "day", 1000, 1005, 995, 1002, 10, None, "test", up_ticks=10, down_ticks=5),
            Bar(start + timedelta(minutes=1), start.date(), "MXF1", "202401", "day", 1003, 1008, 998, 1004, 10, None, "test", up_ticks=10, down_ticks=5),
            Bar(start + timedelta(minutes=5), start.date(), "MXF1", "202401", "day", 1004, 1010, 1000, 1008, 10, None, "test", up_ticks=10, down_ticks=5),
            Bar(start + timedelta(minutes=6), start.date(), "MXF1", "202401", "day", 1009, 1012, 1005, 1010, 10, None, "test", up_ticks=10, down_ticks=5),
            Bar(datetime(2024, 1, 1, 13, 30), start.date(), "MXF1", "202401", "day", 1011, 1013, 1008, 1012, 10, None, "test", up_ticks=10, down_ticks=5),
            Bar(datetime(2024, 1, 1, 13, 31), start.date(), "MXF1", "202401", "day", 1012, 1014, 1010, 1013, 10, None, "test", up_ticks=10, down_ticks=5),
        ]
        extras = {
            start: {"ref_growth_5m": 0.35, "ref_tick_bias_ratio_5m": 0.2},
            start + timedelta(minutes=5): {"ref_growth_5m": 0.4, "ref_tick_bias_ratio_5m": 0.25},
        }
        result = run_backtest(
            bars=bars,
            strategy=strategy,
            config=BacktestConfig(starting_cash=1000),
            context_extras_by_ts=extras,
        )
        self.assertEqual(len(result.fills), 3)
        self.assertEqual(result.fills[0].side, Side.BUY)
        self.assertEqual(result.fills[1].side, Side.BUY)
        self.assertEqual(result.fills[2].side, Side.SELL)
        self.assertEqual(result.fills[2].ts, datetime(2024, 1, 1, 13, 30))
        self.assertEqual(result.fills[2].size, 2)

    def test_mxf_2330_pulse_strategy_triggers_stop_loss_same_bar(self) -> None:
        strategy = Mxf2330PulseStrategy(
            growth_threshold=0.3,
            max_position=2,
            stop_loss_points=100.0,
            force_exit_time="13:30",
        )
        start = datetime(2024, 1, 1, 9, 4)
        bars = [
            Bar(start, start.date(), "MXF1", "202401", "day", 1000, 1005, 995, 1002, 10, None, "test", up_ticks=10, down_ticks=5),
            Bar(start + timedelta(minutes=1), start.date(), "MXF1", "202401", "day", 1003, 1008, 998, 1004, 10, None, "test", up_ticks=10, down_ticks=5),
            Bar(start + timedelta(minutes=2), start.date(), "MXF1", "202401", "day", 1004, 1006, 899, 905, 10, None, "test", up_ticks=1, down_ticks=20),
        ]
        extras = {
            start: {"ref_growth_5m": 0.35, "ref_tick_bias_ratio_5m": 0.2},
        }
        result = run_backtest(
            bars=bars,
            strategy=strategy,
            config=BacktestConfig(starting_cash=1000),
            context_extras_by_ts=extras,
        )
        self.assertEqual(len(result.fills), 2)
        self.assertEqual(result.fills[1].side, Side.SELL)
        self.assertEqual(result.fills[1].ts, start + timedelta(minutes=2))
        self.assertEqual(result.fills[1].price, 903.0)


if __name__ == "__main__":
    unittest.main()
