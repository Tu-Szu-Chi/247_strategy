from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta

from qt_platform.backtest.engine import BacktestConfig, run_backtest
from qt_platform.maintenance.service import MaintenanceService
from qt_platform.providers.finmind import FinMindAdapter
from qt_platform.reporting.performance import write_html_report
from qt_platform.settings import Settings, load_settings
from qt_platform.storage.factory import build_bar_repository
from qt_platform.strategies.sma_cross import SmaCrossStrategy


def main() -> None:
    parser = argparse.ArgumentParser(prog="qt-platform")
    parser.add_argument("--config", default="config/config.yaml")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan-gaps")
    scan.add_argument("--database-url")
    scan.add_argument("--symbol", required=True)
    scan.add_argument("--start", required=True)
    scan.add_argument("--end", required=True)
    scan.add_argument("--step-minutes", type=int, default=1)

    backfill = subparsers.add_parser("backfill")
    backfill.add_argument("--database-url")
    backfill.add_argument("--symbol", required=True)
    backfill.add_argument("--start-date", required=True)
    backfill.add_argument("--end-date", required=True)
    backfill.add_argument("--session-scope", default="day_and_night")
    backfill.add_argument("--timeframe", default="1d")

    backtest = subparsers.add_parser("backtest")
    backtest.add_argument("--database-url")
    backtest.add_argument("--symbol", required=True)
    backtest.add_argument("--start", required=True)
    backtest.add_argument("--end", required=True)
    backtest.add_argument("--timeframe", default="1m")
    backtest.add_argument("--report-dir")
    backtest.add_argument("--strategy", default="sma-cross")
    backtest.add_argument("--fast-window", type=int, default=5)
    backtest.add_argument("--slow-window", type=int, default=20)

    args = parser.parse_args()
    settings = load_settings(args.config)
    if args.command == "scan-gaps":
        _scan_gaps(args, settings)
    elif args.command == "backfill":
        _backfill(args, settings)
    elif args.command == "backtest":
        _backtest(args, settings)


def _scan_gaps(args: argparse.Namespace, settings: Settings) -> None:
    store = build_bar_repository(_database_url(args, settings))
    service = MaintenanceService(provider=_dummy_provider(settings), store=store)
    gaps = service.scan_gaps(
        symbol=args.symbol,
        start=datetime.fromisoformat(args.start),
        end=datetime.fromisoformat(args.end),
        expected_step=timedelta(minutes=args.step_minutes),
    )
    for gap in gaps:
        print(f"{gap.start.isoformat()} -> {gap.end.isoformat()}")


def _backfill(args: argparse.Namespace, settings: Settings) -> None:
    store = build_bar_repository(_database_url(args, settings))
    service = MaintenanceService(provider=_provider(settings), store=store)
    inserted = service.backfill(
        symbol=args.symbol,
        start_date=date.fromisoformat(args.start_date),
        end_date=date.fromisoformat(args.end_date),
        timeframe=args.timeframe,
        session_scope=args.session_scope,
    )
    print(f"upserted_bars={inserted}")


def _backtest(args: argparse.Namespace, settings: Settings) -> None:
    store = build_bar_repository(_database_url(args, settings))
    bars = store.list_bars(
        timeframe=args.timeframe,
        symbol=args.symbol,
        start=datetime.fromisoformat(args.start),
        end=datetime.fromisoformat(args.end),
    )
    strategy = SmaCrossStrategy(fast_window=args.fast_window, slow_window=args.slow_window)
    result = run_backtest(bars=bars, strategy=strategy, config=BacktestConfig())
    report = write_html_report(result, _report_dir(args, settings), f"{args.symbol}-backtest")
    print(f"ending_cash={result.ending_cash:.2f}")
    print(f"report={report}")


def _provider(settings: Settings) -> FinMindAdapter:
    return FinMindAdapter(settings.finmind)


def _dummy_provider(settings: Settings) -> FinMindAdapter:
    # The scan-gaps workflow does not fetch remote data, but the service requires a provider.
    return _provider(settings)


def _database_url(args: argparse.Namespace, settings: Settings) -> str:
    return args.database_url or settings.database.url


def _report_dir(args: argparse.Namespace, settings: Settings) -> str:
    return args.report_dir or settings.reporting.output_dir


if __name__ == "__main__":
    main()
