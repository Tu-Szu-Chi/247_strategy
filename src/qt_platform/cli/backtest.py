from __future__ import annotations

import argparse
from datetime import datetime

from qt_platform.backtest.engine import BacktestConfig, run_backtest
from qt_platform.cli.common import add_common_args, get_database_url
from qt_platform.contracts import root_symbol_for, select_symbol_view
from qt_platform.monitor import MonitorReplayService
from qt_platform.reporting.performance import (
    write_annotated_fill_summary_csv,
    write_backtest_report_bundle,
)
from qt_platform.settings import Settings
from qt_platform.storage.factory import build_bar_repository
from qt_platform.strategies.sma_cross import SmaCrossStrategy


def register_backtest_commands(subparsers):
    backtest_parser = subparsers.add_parser("backtest", help="Strategy backtesting")
    backtest_subparsers = backtest_parser.add_subparsers(dest="backtest_command", required=True)

    run = backtest_subparsers.add_parser("run", help="Run a backtest strategy")
    add_common_args(run)
    run.add_argument("--symbol", required=True)
    run.add_argument("--start", required=True)
    run.add_argument("--end", required=True)
    run.add_argument("--timeframe", default="1m")
    run.add_argument("--report-dir")
    run.add_argument("--strategy", default="sma-cross")
    run.add_argument("--fast-window", type=int, default=5)
    run.add_argument("--slow-window", type=int, default=20)
    run.add_argument("--trade-size", type=int, default=1)
    run.add_argument("--with-option-power-indicators", action="store_true")
    run.add_argument("--option-root", default="AUTO")
    run.add_argument("--expiry-count", type=int, default=2)
    run.add_argument("--indicator-snapshot-interval-seconds", type=float, default=60.0)
    run.add_argument("--fill-summary-csv", action="store_true")


def handle_backtest_command(args: argparse.Namespace, settings: Settings):
    if args.backtest_command == "run":
        _handle_run(args, settings)


def _handle_run(args: argparse.Namespace, settings: Settings):
    store = build_bar_repository(get_database_url(args, settings))
    start = datetime.fromisoformat(args.start)
    end = datetime.fromisoformat(args.end)
    
    bars = store.list_bars(
        timeframe=args.timeframe,
        symbol=root_symbol_for(args.symbol),
        start=start,
        end=end,
    )
    bars = select_symbol_view(args.symbol, bars)
    
    strategy = _build_strategy(args)
    indicator_series = _build_backtest_indicator_series(args, store, start, end)
    
    result = run_backtest(
        bars=bars,
        strategy=strategy,
        config=BacktestConfig(),
        indicator_series=indicator_series,
    )
    
    report_dir = args.report_dir or settings.reporting.output_dir
    report_name = f"{args.symbol}-backtest"
    report, report_json = write_backtest_report_bundle(result, report_dir, report_name)
    
    print(f"Ending Cash: {result.ending_cash:.2f}")
    print(f"Report: {report}")
    if getattr(args, "fill_summary_csv", False):
        fill_summary = write_annotated_fill_summary_csv(result, report_dir, report_name)
        print(f"Fill Summary: {fill_summary}")


def _build_strategy(args: argparse.Namespace):
    if args.strategy == "sma-cross":
        return SmaCrossStrategy(fast_window=args.fast_window, slow_window=args.slow_window)
    raise ValueError(f"Unsupported strategy: {args.strategy}")


def _build_backtest_indicator_series(args, store, start, end):
    if not getattr(args, "with_option_power_indicators", False):
        return None
        
    replay = MonitorReplayService(
        store=store,
        option_root=args.option_root,
        expiry_count=args.expiry_count,
        underlying_symbol=root_symbol_for(args.symbol),
        snapshot_interval_seconds=args.indicator_snapshot_interval_seconds,
    )
    return replay.build_backtest_indicator_series(
        start=start,
        end=end,
        interval=args.timeframe,
    )
