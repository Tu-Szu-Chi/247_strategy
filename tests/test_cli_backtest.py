import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from qt_platform.cli.main import _backtest
from qt_platform.domain import Bar


class BacktestCliTest(unittest.TestCase):
    def test_backtest_can_build_option_power_indicator_series(self) -> None:
        start = datetime(2026, 4, 16, 9, 0, 0)
        end = start + timedelta(minutes=2)
        store = MagicMock()
        store.list_bars.return_value = [
            Bar(start, date(2026, 4, 16), "MTX", "202604", "day", 100, 101, 99, 100, 10, None, "test"),
        ]
        replay = MagicMock()
        replay.build_backtest_indicator_series.return_value = {
            "signal_state": [{"time": start.isoformat(), "value": 1}],
        }
        result = SimpleNamespace(ending_cash=1000.0)
        args = _args(
            start=start,
            end=end,
            with_option_power_indicators=True,
            indicator_series="signal_state,bias_signal",
        )

        with patch("qt_platform.cli.main.build_bar_repository", return_value=store), patch(
            "qt_platform.cli.main.OptionPowerReplayService", return_value=replay
        ) as replay_service, patch("qt_platform.cli.main.run_backtest", return_value=result) as run, patch(
            "qt_platform.cli.main.write_backtest_report_bundle",
            return_value=("report.html", "report.json"),
        ), patch("qt_platform.cli.main.write_annotated_fill_summary_csv") as fill_summary:
            _backtest(args, _settings())

        replay_service.assert_called_once_with(
            store=store,
            option_root="AUTO",
            expiry_count=2,
            underlying_symbol="MTX",
            snapshot_interval_seconds=60.0,
        )
        replay.build_backtest_indicator_series.assert_called_once_with(
            start=start,
            end=end,
            names=["signal_state", "bias_signal"],
            interval="1m",
            wait_timeout=3.0,
        )
        self.assertEqual(run.call_args.kwargs["indicator_series"], replay.build_backtest_indicator_series.return_value)
        fill_summary.assert_not_called()

    def test_backtest_leaves_option_power_indicators_disabled_by_default(self) -> None:
        start = datetime(2026, 4, 16, 9, 0, 0)
        end = start + timedelta(minutes=2)
        store = MagicMock()
        store.list_bars.return_value = [
            Bar(start, date(2026, 4, 16), "MTX", "202604", "day", 100, 101, 99, 100, 10, None, "test"),
        ]
        result = SimpleNamespace(ending_cash=1000.0)

        with patch("qt_platform.cli.main.build_bar_repository", return_value=store), patch(
            "qt_platform.cli.main.OptionPowerReplayService"
        ) as replay_service, patch("qt_platform.cli.main.run_backtest", return_value=result) as run, patch(
            "qt_platform.cli.main.write_backtest_report_bundle",
            return_value=("report.html", "report.json"),
        ), patch("qt_platform.cli.main.write_annotated_fill_summary_csv") as fill_summary:
            _backtest(_args(start=start, end=end), _settings())

        replay_service.assert_not_called()
        self.assertIsNone(run.call_args.kwargs["indicator_series"])
        fill_summary.assert_not_called()

    def test_option_power_signal_strategy_builds_indicators_without_extra_flag(self) -> None:
        start = datetime(2026, 4, 16, 9, 0, 0)
        end = start + timedelta(minutes=2)
        store = MagicMock()
        store.list_bars.return_value = [
            Bar(start, date(2026, 4, 16), "MTX", "202604", "day", 100, 101, 99, 100, 10, None, "test"),
        ]
        replay = MagicMock()
        replay.build_backtest_indicator_series.return_value = {
            "signal_state": [{"time": start.isoformat(), "value": 1}],
        }
        result = SimpleNamespace(ending_cash=1000.0)
        args = _args(start=start, end=end)
        args.strategy = "option-power-signal"

        with patch("qt_platform.cli.main.build_bar_repository", return_value=store), patch(
            "qt_platform.cli.main.OptionPowerReplayService", return_value=replay
        ), patch("qt_platform.cli.main.run_backtest", return_value=result) as run, patch(
            "qt_platform.cli.main.write_backtest_report_bundle",
            return_value=("report.html", "report.json"),
        ), patch(
            "qt_platform.cli.main.write_annotated_fill_summary_csv",
            return_value="fills.csv",
        ) as fill_summary:
            _backtest(args, _settings())

        replay.build_backtest_indicator_series.assert_called_once()
        self.assertEqual(run.call_args.kwargs["strategy"].trade_size, 1)
        self.assertEqual(run.call_args.kwargs["indicator_series"], replay.build_backtest_indicator_series.return_value)
        fill_summary.assert_called_once_with(result, "reports", "MTX-backtest")

    def test_fill_summary_csv_flag_writes_summary_for_any_strategy(self) -> None:
        start = datetime(2026, 4, 16, 9, 0, 0)
        end = start + timedelta(minutes=2)
        store = MagicMock()
        store.list_bars.return_value = [
            Bar(start, date(2026, 4, 16), "MTX", "202604", "day", 100, 101, 99, 100, 10, None, "test"),
        ]
        result = SimpleNamespace(ending_cash=1000.0)
        args = _args(start=start, end=end, fill_summary_csv=True)

        with patch("qt_platform.cli.main.build_bar_repository", return_value=store), patch(
            "qt_platform.cli.main.run_backtest", return_value=result
        ), patch(
            "qt_platform.cli.main.write_backtest_report_bundle",
            return_value=("report.html", "report.json"),
        ), patch(
            "qt_platform.cli.main.write_annotated_fill_summary_csv",
            return_value="fills.csv",
        ) as fill_summary:
            _backtest(args, _settings())

        fill_summary.assert_called_once_with(result, "reports", "MTX-backtest")


def _args(
    *,
    start: datetime,
    end: datetime,
    with_option_power_indicators: bool = False,
    indicator_series: str = "",
    fill_summary_csv: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        database_url="sqlite:///tmp/test.db",
        symbol="MTX",
        start=start.isoformat(),
        end=end.isoformat(),
        timeframe="1m",
        report_dir="reports",
        strategy="sma-cross",
        fast_window=2,
        slow_window=3,
        trade_size=1,
        max_position=1,
        min_force_score=500.0,
        min_tick_bias_ratio=0.1,
        long_only=False,
        reference_symbol="2330",
        with_option_power_indicators=with_option_power_indicators,
        no_bias_alignment=False,
        hold_through_neutral=False,
        option_root="AUTO",
        expiry_count=2,
        indicator_snapshot_interval_seconds=60.0,
        indicator_series=indicator_series,
        indicator_wait_timeout_seconds=3.0,
        fill_summary_csv=fill_summary_csv,
    )


def _settings() -> SimpleNamespace:
    return SimpleNamespace(database=SimpleNamespace(url="sqlite:///tmp/test.db"))


if __name__ == "__main__":
    unittest.main()
