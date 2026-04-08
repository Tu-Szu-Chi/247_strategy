import unittest
from datetime import datetime, timedelta

from qt_platform.backtest.engine import BacktestConfig, run_backtest
from qt_platform.domain import Bar, Side, Signal
from qt_platform.strategies.base import BaseStrategy


class OneShotStrategy(BaseStrategy):
    def __init__(self) -> None:
        self.emitted = False

    def on_bar(self, bar: Bar):
        if self.emitted:
            return []
        self.emitted = True
        return [Signal(ts=bar.ts, side=Side.BUY, size=1, reason="entry")]


class BacktestEngineTest(unittest.TestCase):
    def test_signal_fills_on_next_open(self) -> None:
        start = datetime(2024, 1, 1, 8, 45)
        bars = [
            Bar(start, "TX", "202401", "day", 100, 101, 99, 100, 10, None, "test"),
            Bar(start + timedelta(minutes=1), "TX", "202401", "day", 105, 106, 104, 105, 10, None, "test"),
        ]

        result = run_backtest(bars=bars, strategy=OneShotStrategy(), config=BacktestConfig(starting_cash=1000))

        self.assertEqual(len(result.fills), 1)
        self.assertEqual(result.fills[0].ts, start + timedelta(minutes=1))
        self.assertEqual(result.fills[0].price, 105)


if __name__ == "__main__":
    unittest.main()
