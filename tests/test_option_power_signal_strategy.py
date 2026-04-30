import unittest
from datetime import datetime, timedelta

from qt_platform.backtest.engine import BacktestConfig, run_backtest
from qt_platform.domain import Bar, Side
from qt_platform.strategies.option_power_signal import OptionPowerSignalStrategy


class OptionPowerSignalStrategyTest(unittest.TestCase):
    def test_signal_state_enters_and_neutral_exits(self) -> None:
        start = datetime(2026, 4, 16, 9, 0, 0)
        bars = _bars(start, 4)

        result = run_backtest(
            bars=bars,
            strategy=OptionPowerSignalStrategy(trade_size=1, max_position=1),
            config=BacktestConfig(starting_cash=1000),
            indicator_series={
                "signal_state": [
                    {"time": start.isoformat(), "value": 1},
                    {"time": (start + timedelta(minutes=1)).isoformat(), "value": 1},
                    {"time": (start + timedelta(minutes=2)).isoformat(), "value": 0},
                ],
                "bias_signal": [
                    {"time": start.isoformat(), "value": 1},
                    {"time": (start + timedelta(minutes=1)).isoformat(), "value": 1},
                    {"time": (start + timedelta(minutes=2)).isoformat(), "value": 0},
                ],
                "pressure_index": [
                    {"time": start.isoformat(), "value": 61.25},
                    {"time": (start + timedelta(minutes=2)).isoformat(), "value": 49.0},
                ],
            },
        )

        self.assertEqual([fill.side for fill in result.fills], [Side.BUY, Side.SELL])
        self.assertEqual(result.fills[0].reason, "option_power_signal_long")
        self.assertEqual(result.fills[1].reason, "option_power_signal_flat")
        self.assertEqual(result.fills[0].ts, start + timedelta(minutes=1))
        self.assertEqual(result.fills[1].ts, start + timedelta(minutes=3))
        self.assertEqual(result.fills[0].metadata["signal_state"], 1)
        self.assertEqual(result.fills[0].metadata["bias_signal"], 1)
        self.assertEqual(result.fills[0].metadata["indicator_values"]["pressure_index"], 61.25)
        self.assertEqual(result.fills[1].metadata["signal_state"], 0)

    def test_bias_mismatch_blocks_entry(self) -> None:
        start = datetime(2026, 4, 16, 9, 0, 0)

        result = run_backtest(
            bars=_bars(start, 2),
            strategy=OptionPowerSignalStrategy(),
            config=BacktestConfig(starting_cash=1000),
            indicator_series={
                "signal_state": [{"time": start.isoformat(), "value": 1}],
                "bias_signal": [{"time": start.isoformat(), "value": -1}],
            },
        )

        self.assertEqual(result.fills, [])

    def test_can_enter_short_when_signal_is_negative(self) -> None:
        start = datetime(2026, 4, 16, 9, 0, 0)

        result = run_backtest(
            bars=_bars(start, 2),
            strategy=OptionPowerSignalStrategy(),
            config=BacktestConfig(starting_cash=1000),
            indicator_series={
                "signal_state": [{"time": start.isoformat(), "value": -1}],
                "bias_signal": [{"time": start.isoformat(), "value": -1}],
            },
        )

        self.assertEqual(len(result.fills), 1)
        self.assertEqual(result.fills[0].side, Side.SELL)
        self.assertEqual(result.fills[0].reason, "option_power_signal_short")
        self.assertEqual(result.fills[0].metadata["target_direction"], -1)


def _bars(start: datetime, count: int) -> list[Bar]:
    return [
        Bar(
            start + timedelta(minutes=index),
            start.date(),
            "MTX",
            "202604",
            "day",
            100 + index,
            101 + index,
            99 + index,
            100 + index,
            10,
            None,
            "test",
        )
        for index in range(count)
    ]


if __name__ == "__main__":
    unittest.main()
