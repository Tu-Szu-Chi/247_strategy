from __future__ import annotations

import argparse
import json
import os
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from queue import Empty, Queue
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4
from zoneinfo import ZoneInfo

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None

from qt_platform.backtest.engine import BacktestConfig, run_backtest
from qt_platform.csv_import import import_csv_folder
from qt_platform.domain import LiveRunMetadata
from qt_platform.features import compute_minute_force_feature_series
from qt_platform.live.recorder import LiveRecordResult, LiveRecorderService
from qt_platform.live.shioaji_provider import ShioajiLiveProvider
from qt_platform.live.stub_provider import StubLiveProvider
from qt_platform.option_power import OptionPowerRuntimeService
from qt_platform.contracts import (
    is_continuous_symbol,
    resolve_mtx_monthly_contract,
    root_symbol_for,
    select_symbol_view,
)
from qt_platform.maintenance.service import MaintenanceService
from qt_platform.providers.finmind import FinMindAdapter
from qt_platform.reporting.performance import write_html_report
from qt_platform.session import (
    is_in_activation_scope,
    is_in_session_scope,
    next_activation_start,
    next_session_start,
)
from qt_platform.settings import Settings, load_settings
from qt_platform.storage.factory import build_bar_repository
from qt_platform.strategies.mxf_2330_pulse import Mxf2330PulseStrategy
from qt_platform.strategies.sma_cross import SmaCrossStrategy
from qt_platform.symbol_registry import load_symbol_registry
from qt_platform.sync_executor import sync_registry
from qt_platform.sync_planner import plan_sync
from qt_platform.web import build_option_power_app


LIVE_SUBSCRIBE_LEAD_SECONDS = 20.0


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
    scan.add_argument("--session-scope", default="day_and_night")

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
    backtest.add_argument("--min-force-score", type=float, default=500.0)
    backtest.add_argument("--min-tick-bias-ratio", type=float, default=0.1)
    backtest.add_argument("--long-only", action="store_true")
    backtest.add_argument("--reference-symbol", default="2330")
    backtest.add_argument("--growth-threshold", type=float, default=0.3)
    backtest.add_argument("--max-position", type=int, default=2)
    backtest.add_argument("--stop-loss-points", type=float, default=100.0)
    backtest.add_argument("--force-exit-time", default="13:30")

    doctor = subparsers.add_parser("doctor")
    doctor.add_argument("--database-url")
    doctor.add_argument("--symbol", default="MTX")
    doctor.add_argument("--timeframe", default="1m")

    minute_features = subparsers.add_parser("minute-features")
    minute_features.add_argument("--database-url")
    minute_features.add_argument("--symbol", required=True)
    minute_features.add_argument("--start", required=True)
    minute_features.add_argument("--end", required=True)
    minute_features.add_argument("--limit", type=int, default=20)

    option_minute_features = subparsers.add_parser("option-minute-features")
    option_minute_features.add_argument("--database-url")
    option_minute_features.add_argument("--start", required=True)
    option_minute_features.add_argument("--end", required=True)
    option_minute_features.add_argument("--contract-month")
    option_minute_features.add_argument("--strike-price", type=float)
    option_minute_features.add_argument("--call-put")
    option_minute_features.add_argument("--option-root")
    option_minute_features.add_argument("--expiry-count", type=int, default=2)
    option_minute_features.add_argument("--atm-window", type=int, default=20)
    option_minute_features.add_argument("--underlying-future-symbol", default="TXFR1")
    option_minute_features.add_argument("--limit", type=int, default=20)
    option_minute_features.add_argument("--run-id")

    plan_sync_parser = subparsers.add_parser("plan-sync")
    plan_sync_parser.add_argument("--database-url")
    plan_sync_parser.add_argument("--registry")
    plan_sync_parser.add_argument("--start-date", required=True)
    plan_sync_parser.add_argument("--end-date", required=True)
    plan_sync_parser.add_argument("--timeframes", default="1d,1m")
    plan_sync_parser.add_argument("--requests-per-hour", type=int)
    plan_sync_parser.add_argument("--target-utilization", type=float)

    sync_registry_parser = subparsers.add_parser("sync-registry")
    sync_registry_parser.add_argument("--database-url")
    sync_registry_parser.add_argument("--registry")
    sync_registry_parser.add_argument("--start-date", required=True)
    sync_registry_parser.add_argument("--end-date", required=True)
    sync_registry_parser.add_argument("--timeframes", default="1d,1m")
    sync_registry_parser.add_argument("--session-scope", default="day_and_night")
    sync_registry_parser.add_argument("--requests-per-hour", type=int)
    sync_registry_parser.add_argument("--target-utilization", type=float)
    sync_registry_parser.add_argument("--allow-repair", action="store_true")

    import_csv_parser = subparsers.add_parser("import-csv-folder")
    import_csv_parser.add_argument("--database-url")
    import_csv_parser.add_argument("--folder", required=True)
    import_csv_parser.add_argument("--pattern", default="*.csv")
    import_csv_parser.add_argument("--source", default="broker_csv")
    import_csv_parser.add_argument("--build-source", default="csv_1m_import")
    import_csv_parser.add_argument("--chunk-size", type=int, default=5000)

    record_live_stub = subparsers.add_parser("record-live-stub")
    record_live_stub.add_argument("--database-url")
    record_live_stub.add_argument("--ticks-file", required=True)
    record_live_stub.add_argument("--symbols", required=True)
    record_live_stub.add_argument("--max-events", type=int)

    record_live = subparsers.add_parser("record-live")
    record_live.add_argument("--database-url")
    record_live.add_argument("--provider", default="shioaji")
    record_live.add_argument("--symbols")
    record_live.add_argument("--option-root", default="AUTO")
    record_live.add_argument("--expiry-count", type=int, default=2)
    record_live.add_argument("--atm-window", type=int, default=20)
    record_live.add_argument("--underlying-future-symbol", default="TXFR1")
    record_live.add_argument("--call-put", default="both")
    record_live.add_argument("--max-events", type=int)
    record_live.add_argument("--batch-size", type=int, default=500)
    record_live.add_argument("--idle-timeout-seconds", type=float, default=30.0)
    record_live.add_argument("--simulation", action="store_true")
    record_live.add_argument("--session-scope", default="day_and_night")
    record_live.add_argument("--run-forever", action="store_true")
    record_live.add_argument("--log-file", default="logs/record-live.log")

    record_live_registry = subparsers.add_parser("record-live-registry")
    record_live_registry.add_argument("--database-url")
    record_live_registry.add_argument("--provider", default="shioaji")
    record_live_registry.add_argument("--registry")
    record_live_registry.add_argument("--expiry-count", type=int, default=2)
    record_live_registry.add_argument("--atm-window", type=int, default=20)
    record_live_registry.add_argument("--underlying-future-symbol", default="TXFR1")
    record_live_registry.add_argument("--call-put", default="both")
    record_live_registry.add_argument("--max-events", type=int)
    record_live_registry.add_argument("--batch-size", type=int, default=500)
    record_live_registry.add_argument("--idle-timeout-seconds", type=float, default=30.0)
    record_live_registry.add_argument("--simulation", action="store_true")
    record_live_registry.add_argument("--session-scope", default="day_and_night")
    record_live_registry.add_argument("--run-forever", action="store_true")
    record_live_registry.add_argument("--log-file", default="logs/record-live-registry.log")

    run_runtime = subparsers.add_parser("run-runtime")
    run_runtime.add_argument("--database-url")
    run_runtime.add_argument("--registry")
    run_runtime.add_argument("--history-start-date")
    run_runtime.add_argument("--history-end-date")
    run_runtime.add_argument("--timeframes", default="1d,1m")
    run_runtime.add_argument("--session-scope", default="day_and_night")
    run_runtime.add_argument("--requests-per-hour", type=int)
    run_runtime.add_argument("--target-utilization", type=float)
    run_runtime.add_argument("--allow-repair", action="store_true")
    run_runtime.add_argument("--provider", default="shioaji")
    run_runtime.add_argument("--expiry-count", type=int, default=2)
    run_runtime.add_argument("--atm-window", type=int, default=20)
    run_runtime.add_argument("--underlying-future-symbol", default="TXFR1")
    run_runtime.add_argument("--call-put", default="both")
    run_runtime.add_argument("--max-events", type=int)
    run_runtime.add_argument("--batch-size", type=int, default=500)
    run_runtime.add_argument("--idle-timeout-seconds", type=float, default=30.0)
    run_runtime.add_argument("--simulation", action="store_true")
    run_runtime.add_argument("--run-forever", action="store_true")
    run_runtime.add_argument("--log-file", default="logs/run-runtime.log")

    preview_option_universe = subparsers.add_parser("preview-option-universe")
    preview_option_universe.add_argument("--option-root", default="AUTO")
    preview_option_universe.add_argument("--expiry-count", type=int, default=2)
    preview_option_universe.add_argument("--atm-window", type=int, default=20)
    preview_option_universe.add_argument("--underlying-future-symbol", default="TXFR1")
    preview_option_universe.add_argument("--call-put", default="both")

    serve_option_power = subparsers.add_parser("serve-option-power")
    serve_option_power.add_argument("--database-url")
    serve_option_power.add_argument("--provider", default="shioaji")
    serve_option_power.add_argument("--option-root", default="AUTO")
    serve_option_power.add_argument("--expiry-count", type=int, default=2)
    serve_option_power.add_argument("--atm-window", type=int, default=20)
    serve_option_power.add_argument("--underlying-future-symbol", default="TXFR1")
    serve_option_power.add_argument("--call-put", default="both")
    serve_option_power.add_argument("--batch-size", type=int, default=500)
    serve_option_power.add_argument("--idle-timeout-seconds", type=float, default=30.0)
    serve_option_power.add_argument("--simulation", action="store_true")
    serve_option_power.add_argument("--session-scope", default="day_and_night")
    serve_option_power.add_argument("--host", default="127.0.0.1")
    serve_option_power.add_argument("--port", type=int, default=8000)
    serve_option_power.add_argument("--snapshot-interval-seconds", type=float, default=5.0)
    serve_option_power.add_argument("--ready-timeout-seconds", type=float, default=15.0)
    serve_option_power.add_argument("--log-file", default="logs/serve-option-power.log")

    resolve_contract = subparsers.add_parser("resolve-contract")
    resolve_contract.add_argument("--symbol", default="MTX")
    resolve_contract.add_argument("--date", required=True)

    args = parser.parse_args()
    settings = load_settings(args.config)
    if args.command == "scan-gaps":
        _scan_gaps(args, settings)
    elif args.command == "backfill":
        _backfill(args, settings)
    elif args.command == "backtest":
        _backtest(args, settings)
    elif args.command == "doctor":
        _doctor(args, settings)
    elif args.command == "minute-features":
        _minute_features(args, settings)
    elif args.command == "option-minute-features":
        _option_minute_features(args, settings)
    elif args.command == "plan-sync":
        _plan_sync(args, settings)
    elif args.command == "sync-registry":
        _sync_registry(args, settings)
    elif args.command == "import-csv-folder":
        _import_csv_folder(args, settings)
    elif args.command == "record-live-stub":
        _record_live_stub(args, settings)
    elif args.command == "record-live":
        _record_live(args, settings)
    elif args.command == "record-live-registry":
        _record_live_registry(args, settings)
    elif args.command == "run-runtime":
        _run_runtime(args, settings)
    elif args.command == "preview-option-universe":
        _preview_option_universe(args, settings)
    elif args.command == "serve-option-power":
        _serve_option_power(args, settings)
    elif args.command == "resolve-contract":
        _resolve_contract(args)


def _scan_gaps(args: argparse.Namespace, settings: Settings) -> None:
    store = build_bar_repository(_database_url(args, settings))
    service = MaintenanceService(provider=_dummy_provider(settings), store=store)
    gaps = service.scan_gaps(
        symbol=root_symbol_for(args.symbol),
        start=datetime.fromisoformat(args.start),
        end=datetime.fromisoformat(args.end),
        expected_step=timedelta(minutes=args.step_minutes),
        session_scope=args.session_scope,
    )
    for gap in gaps:
        print(f"{gap.start.isoformat()} -> {gap.end.isoformat()}")


def _backfill(args: argparse.Namespace, settings: Settings) -> None:
    store = build_bar_repository(_database_url(args, settings))
    service = MaintenanceService(provider=_provider(settings), store=store)
    inserted = service.backfill(
        symbol=root_symbol_for(args.symbol),
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
        symbol=root_symbol_for(args.symbol),
        start=datetime.fromisoformat(args.start),
        end=datetime.fromisoformat(args.end),
    )
    bars = select_symbol_view(args.symbol, bars)
    strategy = _build_strategy(args)
    context_extras_by_ts = None
    if args.strategy == "mxf-2330-pulse":
        reference_bars = store.list_bars(
            timeframe="1m",
            symbol=root_symbol_for(args.reference_symbol),
            start=datetime.fromisoformat(args.start),
            end=datetime.fromisoformat(args.end),
        )
        context_extras_by_ts = _build_reference_growth_context(reference_bars)
    result = run_backtest(
        bars=bars,
        strategy=strategy,
        config=BacktestConfig(),
        context_extras_by_ts=context_extras_by_ts,
    )
    report = write_html_report(result, _report_dir(args, settings), f"{args.symbol}-backtest")
    print(f"ending_cash={result.ending_cash:.2f}")
    print(f"report={report}")


def _build_strategy(args: argparse.Namespace):
    if args.strategy == "sma-cross":
        return SmaCrossStrategy(fast_window=args.fast_window, slow_window=args.slow_window)
    raise ValueError(f"Unsupported strategy: {args.strategy}")


def _build_reference_growth_context(bars: list) -> dict[datetime, dict]:
    five_minute = _aggregate_reference_5m(bars)
    context: dict[datetime, dict] = {}
    previous_ratio: float | None = None
    for item in five_minute:
        current_ratio = item["tick_bias_ratio_5m"]
        growth = None
        if previous_ratio is not None and previous_ratio > 0:
            growth = (current_ratio - previous_ratio) / previous_ratio
        context[item["ts"]] = {
            "ref_symbol": item["symbol"],
            "ref_tick_bias_ratio_5m": current_ratio,
            "ref_prev_tick_bias_ratio_5m": previous_ratio,
            "ref_growth_5m": growth,
        }
        previous_ratio = current_ratio
    return context


def _aggregate_reference_5m(bars: list) -> list[dict]:
    buckets: dict[datetime, list] = {}
    for bar in bars:
        if bar.session != "day":
            continue
        bucket_start = bar.ts.replace(minute=(bar.ts.minute // 5) * 5, second=0, microsecond=0)
        buckets.setdefault(bucket_start, []).append(bar)

    aggregated: list[dict] = []
    for bucket_start, bucket_bars in sorted(buckets.items(), key=lambda item: item[0]):
        up_ticks = sum(bar.up_ticks or 0 for bar in bucket_bars)
        down_ticks = sum(bar.down_ticks or 0 for bar in bucket_bars)
        tick_total = up_ticks + down_ticks
        tick_bias_ratio = (up_ticks - down_ticks) / tick_total if tick_total > 0 else 0.0
        aggregated.append(
            {
                "ts": max(bar.ts for bar in bucket_bars),
                "symbol": bucket_bars[-1].symbol,
                "tick_bias_ratio_5m": tick_bias_ratio,
            }
        )
    return aggregated


def _partition_registry_live_entries(entries) -> tuple[list[str], set[str]]:
    exact_symbols: list[str] = []
    option_roots: set[str] = set()
    for entry in entries:
        if entry.instrument_type == "stock":
            exact_symbols.append(entry.symbol)
        elif entry.instrument_type == "future":
            exact_symbols.append(_live_symbol_for_registry_future(entry.symbol))
        elif entry.instrument_type == "option":
            option_roots.add(entry.root_symbol)
    return sorted(set(exact_symbols)), option_roots


def _live_symbol_for_registry_future(symbol: str) -> str:
    mapping = {
        "MTX": "MXFR1",
        "MXF": "MXFR1",
        "TX": "TXFR1",
        "TXF": "TXFR1",
    }
    return mapping.get(symbol, mapping.get(root_symbol_for(symbol), symbol))


def _resolve_registry_live_universe(
    provider: ShioajiLiveProvider,
    exact_symbols: list[str],
    option_roots: set[str],
    expiry_count: int,
    atm_window: int,
    underlying_future_symbol: str,
    call_put: str,
) -> tuple[list, str, str, dict]:
    contracts = [provider._resolve_contract(symbol) for symbol in exact_symbols]
    reference_price: float | None = None
    resolved_option_roots: list[str] = []
    for option_root in sorted(option_roots):
        roots, resolved, option_reference_price = provider.resolve_option_universe(
            option_root=option_root,
            expiry_count=expiry_count,
            atm_window=atm_window,
            underlying_future_symbol=underlying_future_symbol,
            call_put=call_put,
        )
        contracts.extend(resolved)
        resolved_option_roots.extend(roots)
        if reference_price is None:
            reference_price = option_reference_price
    unique_contracts = {}
    for contract in contracts:
        key = str(getattr(contract, "code", None) or getattr(contract, "symbol", None))
        unique_contracts[key] = contract
    contracts = list(unique_contracts.values())
    symbols_json = json.dumps(
        [str(getattr(contract, "symbol", "")) for contract in contracts],
        ensure_ascii=False,
    )
    codes_json = json.dumps(
        [str(getattr(contract, "code", "")) for contract in contracts],
        ensure_ascii=False,
    )
    metadata = {"reference_price": reference_price}
    if resolved_option_roots:
        metadata["resolved_option_roots"] = sorted(set(resolved_option_roots))
    return contracts, symbols_json, codes_json, metadata


def _provider(settings: Settings) -> FinMindAdapter:
    return FinMindAdapter(settings.finmind)


def _dummy_provider(settings: Settings) -> FinMindAdapter:
    # The scan-gaps workflow does not fetch remote data, but the service requires a provider.
    return _provider(settings)


def _database_url(args: argparse.Namespace, settings: Settings) -> str:
    return args.database_url or settings.database.url


def _report_dir(args: argparse.Namespace, settings: Settings) -> str:
    return args.report_dir or settings.reporting.output_dir


def _doctor(args: argparse.Namespace, settings: Settings) -> None:
    database_url = _database_url(args, settings)
    root_symbol = root_symbol_for(args.symbol)
    checks = {
        "config_path": "ok",
        "database_url": database_url,
        "requested_symbol": args.symbol,
        "root_symbol": root_symbol,
        "symbol_mode": "continuous_main_contract" if is_continuous_symbol(args.symbol) else "raw_symbol",
        "finmind_token_present": "ok" if settings.finmind.token else "missing",
        "finmind_user_info": _check_finmind_user_info(settings),
        "database_connectivity": _check_database_connectivity(database_url),
        "schema": _check_schema(database_url),
        "symbol_data": _check_symbol_data(database_url, root_symbol, args.timeframe),
        "latest_bar_ts": _latest_bar_ts(database_url, root_symbol, args.timeframe),
        "latest_trading_day": _latest_trading_day(database_url, root_symbol, args.timeframe),
        "sync_cursor": _sync_cursor(database_url, root_symbol, args.timeframe),
    }
    print(json.dumps(checks, ensure_ascii=False, indent=2, default=str))


def _minute_features(args: argparse.Namespace, settings: Settings) -> None:
    store = build_bar_repository(_database_url(args, settings))
    bars = store.list_bars(
        timeframe="1m",
        symbol=root_symbol_for(args.symbol),
        start=datetime.fromisoformat(args.start),
        end=datetime.fromisoformat(args.end),
    )
    features = compute_minute_force_feature_series(select_symbol_view(args.symbol, bars))
    payload = {
        "symbol": args.symbol,
        "count": len(features),
        "items": [item.to_dict() for item in features[: args.limit]],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _option_minute_features(args: argparse.Namespace, settings: Settings) -> None:
    store = build_bar_repository(_database_url(args, settings))
    start = datetime.fromisoformat(args.start)
    end = datetime.fromisoformat(args.end)
    resolver_payload = None
    allowed_instrument_keys: set[str] | None = None
    allowed_symbols: list[str] | None = None

    if args.run_id:
        metadata = store.get_live_run(args.run_id)
        if metadata is None:
            raise ValueError(f"run_id '{args.run_id}' was not found.")
        allowed_instrument_keys = set(json.loads(metadata.codes_json or "[]"))
        allowed_symbols = sorted({code[:3] for code in allowed_instrument_keys if code})
        resolver_payload = {
            "run_id": metadata.run_id,
            "provider": metadata.provider,
            "mode": metadata.mode,
            "started_at": metadata.started_at.isoformat(),
            "topic_count": metadata.topic_count,
            "option_root": metadata.option_root,
            "expiry_count": metadata.expiry_count,
            "atm_window": metadata.atm_window,
            "underlying_future_symbol": metadata.underlying_future_symbol,
            "call_put": metadata.call_put,
            "reference_price": metadata.reference_price,
            "resolved_count": len(allowed_instrument_keys),
            "resolved_codes": sorted(allowed_instrument_keys),
            "status": metadata.status,
        }
    elif args.option_root:
        provider = ShioajiLiveProvider(settings=settings.shioaji, simulation=False)
        provider.connect()
        try:
            selected_roots, contracts, reference_price = provider.resolve_option_universe(
                option_root=args.option_root,
                expiry_count=args.expiry_count,
                atm_window=args.atm_window,
                underlying_future_symbol=args.underlying_future_symbol,
                call_put=args.call_put or "both",
            )
            usage = provider.usage_status()
        finally:
            provider.close()
        allowed_instrument_keys = {str(getattr(contract, "code", "")) for contract in contracts}
        allowed_symbols = sorted(set(selected_roots))
        resolver_payload = {
            "option_root": args.option_root,
            "selected_roots": selected_roots,
            "expiry_count": args.expiry_count,
            "atm_window": args.atm_window,
            "underlying_future_symbol": args.underlying_future_symbol,
            "call_put": args.call_put or "both",
            "reference_price": reference_price,
            "resolved_count": len(contracts),
            "resolved_codes": sorted(allowed_instrument_keys),
            "usage_status": usage.to_dict() if usage else None,
        }

    features = store.list_minute_force_features(
        symbol=None,
        start=start,
        end=end,
        run_id=args.run_id,
        symbols=allowed_symbols,
        instrument_keys=sorted(allowed_instrument_keys) if allowed_instrument_keys else None,
        contract_month=args.contract_month,
        strike_price=args.strike_price,
        call_put=args.call_put if args.call_put in {"call", "put"} else None,
    )
    payload = {
        "symbol": "AUTO_OPTION_ROOTS",
        "count": len(features),
        "items": [item.to_dict() for item in features[: args.limit]],
    }
    if resolver_payload:
        payload["resolver"] = resolver_payload
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _plan_sync(args: argparse.Namespace, settings: Settings) -> None:
    store = build_bar_repository(_database_url(args, settings))
    registry_path = args.registry or settings.sync.registry_path
    entries = load_symbol_registry(registry_path)
    timeframe_values = [value.strip() for value in args.timeframes.split(",") if value.strip()]
    plan = plan_sync(
        store=store,
        entries=entries,
        start_date=date.fromisoformat(args.start_date),
        end_date=date.fromisoformat(args.end_date),
        timeframes=timeframe_values,
        requests_per_hour=args.requests_per_hour or settings.sync.requests_per_hour,
        target_utilization=args.target_utilization or settings.sync.target_utilization,
    )
    payload = plan.to_dict()
    payload["registry_path"] = registry_path
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _sync_registry(args: argparse.Namespace, settings: Settings) -> None:
    store = build_bar_repository(_database_url(args, settings))
    entries = load_symbol_registry(args.registry or settings.sync.registry_path)
    timeframe_values = [value.strip() for value in args.timeframes.split(",") if value.strip()]
    result = sync_registry(
        store=store,
        provider=_provider(settings),
        entries=entries,
        start_date=date.fromisoformat(args.start_date),
        end_date=date.fromisoformat(args.end_date),
        timeframes=timeframe_values,
        requests_per_hour=args.requests_per_hour or settings.sync.requests_per_hour,
        target_utilization=args.target_utilization or settings.sync.target_utilization,
        session_scope=args.session_scope,
        allow_repair=args.allow_repair,
    )
    payload = result.to_dict()
    payload["registry_path"] = args.registry or settings.sync.registry_path
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _import_csv_folder(args: argparse.Namespace, settings: Settings) -> None:
    store = build_bar_repository(_database_url(args, settings))
    result = import_csv_folder(
        store=store,
        folder=args.folder,
        pattern=args.pattern,
        source=args.source,
        build_source=args.build_source,
        chunk_size=args.chunk_size,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


def _record_live_stub(args: argparse.Namespace, settings: Settings) -> None:
    store = build_bar_repository(_database_url(args, settings))
    provider = StubLiveProvider(args.ticks_file)
    service = LiveRecorderService(provider=provider, store=store)
    symbols = [value.strip() for value in args.symbols.split(",") if value.strip()]
    result = service.record(symbols=symbols, max_events=args.max_events)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


def _record_live(args: argparse.Namespace, settings: Settings) -> None:
    if args.run_forever:
        _record_live_daemon(args, settings)
        return
    result = _run_live_record_cycle(args, settings)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


def _record_live_registry(args: argparse.Namespace, settings: Settings) -> None:
    if args.run_forever:
        _record_live_daemon(args, settings)
        return
    result = _run_live_record_cycle(args, settings)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


def _run_runtime(args: argparse.Namespace, settings: Settings) -> None:
    registry_path = args.registry or settings.sync.registry_path
    today = datetime.now(ZoneInfo(settings.app.timezone)).date()
    start_date = date.fromisoformat(args.history_start_date) if args.history_start_date else today - timedelta(days=365 * 3)
    end_date = date.fromisoformat(args.history_end_date) if args.history_end_date else today - timedelta(days=1)
    timeframe_values = [value.strip() for value in args.timeframes.split(",") if value.strip()]
    exceptions: Queue[BaseException] = Queue()
    results: Queue[dict] = Queue()

    def history_worker() -> None:
        try:
            store = build_bar_repository(_database_url(args, settings))
            all_entries = load_symbol_registry(registry_path)
            provider = _provider(settings)
            entries = []
            for entry in all_entries:
                if any(
                    provider.supports_history(
                        market=entry.market,
                        instrument_type=entry.instrument_type,
                        symbol=entry.root_symbol,
                        timeframe=timeframe,
                    )
                    for timeframe in timeframe_values
                ):
                    entries.append(entry)
                else:
                    _emit_runtime_status(
                        {
                            "status": "history_item_skipped",
                            "symbol": entry.symbol,
                            "root_symbol": entry.root_symbol,
                            "market": entry.market,
                            "instrument_type": entry.instrument_type,
                            "timeframe": ",".join(timeframe_values),
                            "action": "skipped_unsupported",
                            "reason": "unsupported_for_requested_timeframes",
                        },
                        args.log_file,
                    )
            def progress_callback(payload: dict) -> None:
                _emit_runtime_status(payload, args.log_file)
            _emit_runtime_status(
                {
                    "status": "history_sync_started",
                    "registry_path": registry_path,
                    "history_start_date": start_date.isoformat(),
                    "history_end_date": end_date.isoformat(),
                    "timeframes": timeframe_values,
                },
                args.log_file,
            )
            sync_result = sync_registry(
                store=store,
                provider=provider,
                entries=entries,
                start_date=start_date,
                end_date=end_date,
                timeframes=timeframe_values,
                requests_per_hour=args.requests_per_hour or settings.sync.requests_per_hour,
                target_utilization=args.target_utilization or settings.sync.target_utilization,
                session_scope=args.session_scope,
                allow_repair=args.allow_repair,
                progress_callback=progress_callback,
            )
            payload = {
                "status": "history_sync_completed",
                "registry_path": registry_path,
                "history_start_date": start_date.isoformat(),
                "history_end_date": end_date.isoformat(),
                "timeframes": timeframe_values,
                "items": [item.__dict__ for item in sync_result.items],
            }
            _emit_runtime_status(payload, args.log_file)
            results.put({"history": payload})
        except BaseException as exc:  # pragma: no cover - surfaced in main thread
            _emit_runtime_status(
                {
                    "status": "history_sync_error",
                    "registry_path": registry_path,
                    "message": str(exc),
                },
                args.log_file,
            )
            exceptions.put(exc)

    def live_worker() -> None:
        live_args = argparse.Namespace(**vars(args))
        live_args.registry = registry_path
        try:
            if args.run_forever:
                _record_live_daemon(live_args, settings)
                return
            result = _run_live_record_cycle(live_args, settings)
            payload = result.to_dict()
            _emit_runtime_status(payload, args.log_file)
            results.put({"live": payload})
        except BaseException as exc:  # pragma: no cover - surfaced in main thread
            _emit_runtime_status(
                {
                    "status": "live_runtime_error",
                    "registry_path": registry_path,
                    "message": str(exc),
                },
                args.log_file,
            )
            exceptions.put(exc)

    history_thread = threading.Thread(
        target=history_worker,
        name="history-sync-thread",
        daemon=args.run_forever,
    )
    live_thread = threading.Thread(
        target=live_worker,
        name="live-recorder-thread",
        daemon=False,
    )
    history_thread.start()
    live_thread.start()

    collected: dict[str, dict] = {}
    while history_thread.is_alive() or live_thread.is_alive():
        try:
            exc = exceptions.get_nowait()
            raise exc
        except Empty:
            pass
        try:
            payload = results.get(timeout=0.5)
            collected.update(payload)
        except Empty:
            pass

    history_thread.join()
    live_thread.join()

    try:
        exc = exceptions.get_nowait()
        raise exc
    except Empty:
        pass

    while True:
        try:
            payload = results.get_nowait()
            collected.update(payload)
        except Empty:
            break

    if not args.run_forever:
        print(json.dumps(collected, ensure_ascii=False, indent=2))


def _run_live_record_cycle(args: argparse.Namespace, settings: Settings) -> LiveRecordResult:
    if args.provider != "shioaji":
        raise ValueError("Only provider=shioaji is implemented in v1.")
    store = build_bar_repository(_database_url(args, settings))
    provider = ShioajiLiveProvider(
        settings=settings.shioaji,
        idle_timeout_seconds=args.idle_timeout_seconds,
        simulation=args.simulation,
    )
    service = LiveRecorderService(provider=provider, store=store)
    run_id = _new_live_run_id()
    if getattr(args, "registry", None):
        entries = load_symbol_registry(args.registry)
        provider.connect()
        _emit_runtime_status(
            {"status": "connected", "provider": "shioaji", "simulation": args.simulation, "run_id": run_id},
            args.log_file if hasattr(args, "log_file") else None,
        )
        try:
            exact_symbols, option_roots = _partition_registry_live_entries(entries)
            contracts, symbols_json, codes_json, extra_metadata = _resolve_registry_live_universe(
                provider=provider,
                exact_symbols=exact_symbols,
                option_roots=option_roots,
                expiry_count=args.expiry_count,
                atm_window=args.atm_window,
                underlying_future_symbol=args.underlying_future_symbol,
                call_put=args.call_put,
            )
            metadata = LiveRunMetadata(
                run_id=run_id,
                provider="shioaji",
                mode="registry_runtime",
                started_at=datetime.now(),
                session_scope=args.session_scope,
                topic_count=len(contracts),
                symbols_json=symbols_json,
                codes_json=codes_json,
                option_root=",".join(extra_metadata.get("resolved_option_roots", sorted(option_roots))) if option_roots else None,
                underlying_future_symbol=args.underlying_future_symbol if option_roots else None,
                expiry_count=args.expiry_count if option_roots else None,
                atm_window=args.atm_window if option_roots else None,
                call_put=args.call_put if option_roots else None,
                reference_price=extra_metadata.get("reference_price"),
                status="started",
            )
            store.create_live_run(metadata)
            _emit_runtime_status(
                {
                    "status": "subscribed",
                    "run_id": run_id,
                    "topic_count": len(contracts),
                    "exact_symbols": exact_symbols,
                    "option_roots": extra_metadata.get("resolved_option_roots", sorted(option_roots)),
                },
                args.log_file if hasattr(args, "log_file") else None,
            )
            usage_before = provider.usage_status()
            result = service.persist_tick_stream(
                provider.stream_ticks_from_contracts(contracts=contracts, max_events=args.max_events),
                usage_before=usage_before,
                batch_size=args.batch_size,
                run_id=run_id,
            )
            usage_after = provider.usage_status()
        except Exception:
            if "metadata" in locals():
                store.create_live_run(LiveRunMetadata(**{**metadata.__dict__, "status": "error"}))
            stop_reason = provider.stop_reason()
            provider.close()
            raise
        finally:
            stop_reason = provider.stop_reason()
            provider.close()
        final_status = stop_reason or "completed"
        store.create_live_run(LiveRunMetadata(**{**metadata.__dict__, "status": final_status}))
        result = LiveRecordResult(
            run_id=run_id,
            ticks_appended=result.ticks_appended,
            bars_upserted=result.bars_upserted,
            first_tick_ts=result.first_tick_ts,
            last_tick_ts=result.last_tick_ts,
            stop_reason=stop_reason,
            usage_status=(usage_after or usage_before).to_dict() if (usage_after or usage_before) else None,
        )
    elif args.symbols:
        symbols = [value.strip() for value in args.symbols.split(",") if value.strip()]
        provider.connect()
        _emit_runtime_status(
            {"status": "connected", "provider": "shioaji", "simulation": args.simulation, "run_id": run_id},
            args.log_file if hasattr(args, "log_file") else None,
        )
        metadata = LiveRunMetadata(
            run_id=run_id,
            provider="shioaji",
            mode="exact_symbols",
            started_at=datetime.now(),
            session_scope=args.session_scope,
            topic_count=len(symbols),
            symbols_json=json.dumps(symbols, ensure_ascii=False),
            status="started",
        )
        store.create_live_run(metadata)
        _emit_runtime_status(
            {"status": "subscribed", "run_id": run_id, "topic_count": len(symbols), "symbols": symbols},
            args.log_file if hasattr(args, "log_file") else None,
        )
        try:
            usage_before = provider.usage_status()
            result = service.persist_tick_stream(
                provider.stream_ticks(symbols=symbols, max_events=args.max_events),
                usage_before=usage_before,
                batch_size=args.batch_size,
                run_id=run_id,
            )
            usage_after = provider.usage_status()
            stop_reason = provider.stop_reason()
        except Exception:
            store.create_live_run(LiveRunMetadata(**{**metadata.__dict__, "status": "error"}))
            provider.close()
            raise
        provider.close()
        final_status = stop_reason or "completed"
        store.create_live_run(LiveRunMetadata(**{**metadata.__dict__, "status": final_status}))
        result = LiveRecordResult(
            run_id=run_id,
            ticks_appended=result.ticks_appended,
            bars_upserted=result.bars_upserted,
            first_tick_ts=result.first_tick_ts,
            last_tick_ts=result.last_tick_ts,
            stop_reason=stop_reason,
            usage_status=(usage_after or usage_before).to_dict() if (usage_after or usage_before) else None,
        )
    elif args.option_root:
        provider.connect()
        _emit_runtime_status(
            {"status": "connected", "provider": "shioaji", "simulation": args.simulation, "run_id": run_id},
            args.log_file if hasattr(args, "log_file") else None,
        )
        try:
            selected_roots, contracts, reference_price = provider.resolve_option_universe(
                option_root=args.option_root,
                expiry_count=args.expiry_count,
                atm_window=args.atm_window,
                underlying_future_symbol=args.underlying_future_symbol,
                call_put=args.call_put,
            )
            symbols = [str(getattr(contract, "symbol", "")) for contract in contracts]
            codes = [str(getattr(contract, "code", "")) for contract in contracts]
            metadata = LiveRunMetadata(
                run_id=run_id,
                provider="shioaji",
                mode="option_resolver",
                started_at=datetime.now(),
                session_scope=args.session_scope,
                topic_count=len(contracts),
                symbols_json=json.dumps(symbols, ensure_ascii=False),
                codes_json=json.dumps(codes, ensure_ascii=False),
                option_root=",".join(selected_roots),
                underlying_future_symbol=args.underlying_future_symbol,
                expiry_count=args.expiry_count,
                atm_window=args.atm_window,
                call_put=args.call_put,
                reference_price=reference_price,
                status="started",
            )
            store.create_live_run(metadata)
            _emit_runtime_status(
                {
                    "status": "subscribed",
                    "run_id": run_id,
                    "topic_count": len(contracts),
                    "option_roots": selected_roots,
                    "expiry_count": args.expiry_count,
                    "atm_window": args.atm_window,
                    "reference_price": reference_price,
                },
                args.log_file if hasattr(args, "log_file") else None,
            )
            usage_before = provider.usage_status()
            result = service.persist_tick_stream(
                provider.stream_ticks_from_contracts(contracts=contracts, max_events=args.max_events),
                usage_before=usage_before,
                batch_size=args.batch_size,
                run_id=run_id,
            )
            usage_after = provider.usage_status()
        except Exception:
            if 'metadata' in locals():
                store.create_live_run(LiveRunMetadata(**{**metadata.__dict__, "status": "error"}))
            stop_reason = provider.stop_reason()
            provider.close()
            raise
        finally:
            stop_reason = provider.stop_reason()
            provider.close()
        final_status = stop_reason or "completed"
        store.create_live_run(LiveRunMetadata(**{**metadata.__dict__, "status": final_status}))
        result = LiveRecordResult(
            run_id=run_id,
            ticks_appended=result.ticks_appended,
            bars_upserted=result.bars_upserted,
            first_tick_ts=result.first_tick_ts,
            last_tick_ts=result.last_tick_ts,
            stop_reason=stop_reason,
            usage_status=(usage_after or usage_before).to_dict() if (usage_after or usage_before) else None,
        )
    else:
        raise ValueError("Either --symbols or --option-root must be provided.")
    return result


def _record_live_daemon(args: argparse.Namespace, settings: Settings) -> None:
    timezone = ZoneInfo(settings.app.timezone)
    while True:
        now = datetime.now(timezone)
        local_now = now.replace(tzinfo=None)
        if not is_in_activation_scope(local_now, args.session_scope, lead_seconds=LIVE_SUBSCRIBE_LEAD_SECONDS):
            wake_at = next_activation_start(
                local_now,
                args.session_scope,
                lead_seconds=LIVE_SUBSCRIBE_LEAD_SECONDS,
            ).replace(tzinfo=timezone)
            session_wake_at = next_session_start(local_now, args.session_scope).replace(tzinfo=timezone)
            _emit_runtime_status(
                {
                    "status": "waiting_for_session",
                    "now": now.isoformat(),
                    "wake_at": wake_at.isoformat(),
                    "session_wake_at": session_wake_at.isoformat(),
                    "subscribe_lead_seconds": LIVE_SUBSCRIBE_LEAD_SECONDS,
                    "session_scope": args.session_scope,
                },
                args.log_file,
            )
            _sleep_until(wake_at)
            continue

        result = _run_live_record_cycle(args, settings)
        _emit_runtime_status(result.to_dict(), args.log_file)

        if result.stop_reason == "usage_threshold_reached":
            wake_at = _next_usage_reset_at(now, settings)
            _emit_runtime_status(
                {
                    "status": "waiting_for_usage_reset",
                    "now": now.isoformat(),
                    "wake_at": wake_at.isoformat(),
                },
                args.log_file,
            )
            _sleep_until(wake_at)
            continue

        if result.ticks_appended == 0:
            idle_seconds = max(args.idle_timeout_seconds, 5.0)
            time.sleep(idle_seconds)


def _next_usage_reset_at(now: datetime, settings: Settings) -> datetime:
    timezone = ZoneInfo(settings.app.timezone)
    local_now = now.astimezone(timezone)
    candidate = local_now.replace(
        hour=settings.shioaji.usage_reset_hour,
        minute=settings.shioaji.usage_reset_minute,
        second=0,
        microsecond=0,
    )
    if candidate <= local_now:
        candidate += timedelta(days=1)
    candidate += timedelta(seconds=settings.shioaji.usage_reset_buffer_seconds)
    return candidate


def _sleep_until(target: datetime) -> None:
    while True:
        now = datetime.now(target.tzinfo)
        remaining = (target - now).total_seconds()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 60.0))


def _emit_runtime_status(payload: dict, log_file: str | None) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    if not log_file:
        return
    path = Path(log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, default=str))
        fh.write(os.linesep)


def _new_live_run_id() -> str:
    return f"live-{datetime.now().strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}"


def _preview_option_universe(args: argparse.Namespace, settings: Settings) -> None:
    provider = ShioajiLiveProvider(settings=settings.shioaji, simulation=False)
    provider.connect()
    try:
        selected_roots, contracts, reference_price = provider.resolve_option_universe(
            option_root=args.option_root,
            expiry_count=args.expiry_count,
            atm_window=args.atm_window,
            underlying_future_symbol=args.underlying_future_symbol,
            call_put=args.call_put,
        )
        usage = provider.usage_status()
    finally:
        provider.close()

    payload = {
        "option_root": args.option_root,
        "selected_roots": selected_roots,
        "expiry_count": args.expiry_count,
        "atm_window": args.atm_window,
        "underlying_future_symbol": args.underlying_future_symbol,
        "call_put": args.call_put,
        "reference_price": reference_price,
        "count": len(contracts),
        "symbols": [getattr(contract, "symbol", None) for contract in contracts],
        "codes": [getattr(contract, "code", None) for contract in contracts],
        "usage_status": usage.to_dict() if usage else None,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _serve_option_power(args: argparse.Namespace, settings: Settings) -> None:
    if args.provider != "shioaji":
        raise ValueError("Only provider=shioaji is implemented in v1.")
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "uvicorn is required for serve-option-power. Install with: pip install -e .[web]"
        ) from exc

    provider = ShioajiLiveProvider(
        settings=settings.shioaji,
        idle_timeout_seconds=args.idle_timeout_seconds,
        simulation=args.simulation,
    )
    store = build_bar_repository(_database_url(args, settings))
    runtime = OptionPowerRuntimeService(
        provider=provider,
        store=store,
        option_root=args.option_root,
        expiry_count=args.expiry_count,
        atm_window=args.atm_window,
        underlying_future_symbol=args.underlying_future_symbol,
        call_put=args.call_put,
        session_scope=args.session_scope,
        batch_size=args.batch_size,
        snapshot_interval_seconds=args.snapshot_interval_seconds,
        log_callback=lambda payload: _emit_runtime_status(payload, args.log_file),
    )
    run_id = _new_live_run_id()
    runtime.start(run_id=run_id)
    if not runtime.wait_until_ready(timeout=args.ready_timeout_seconds):
        raise RuntimeError("Option power runtime did not become ready within timeout.")
    if runtime.status not in {"running", "waiting_for_session"}:
        raise RuntimeError(runtime.error_message or f"Option power runtime failed with status={runtime.status}.")

    app = build_option_power_app(runtime)
    _emit_runtime_status(
        {
            "status": "web_ready",
            "run_id": run_id,
            "host": args.host,
            "port": args.port,
            "url": f"http://{args.host}:{args.port}/",
        },
        args.log_file,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info", access_log=False)


def _resolve_contract(args: argparse.Namespace) -> None:
    if args.symbol != "MTX":
        raise ValueError("Only MTX monthly contract resolution is implemented in v1.")
    resolution = resolve_mtx_monthly_contract(date.fromisoformat(args.date))
    print(json.dumps(resolution.__dict__, ensure_ascii=False, indent=2, default=str))


def _check_finmind_user_info(settings: Settings) -> dict:
    if not settings.finmind.token:
        return {"status": "missing_token"}

    req = Request(
        "https://api.web.finmindtrade.com/v2/user_info",
        headers={"Authorization": f"Bearer {settings.finmind.token}"},
    )
    try:
        with urlopen(req, timeout=settings.finmind.timeout_seconds) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return {
            "status": payload.get("status"),
            "level_title": payload.get("level_title"),
            "api_request_limit_hour": payload.get("api_request_limit_hour"),
            "user_count": payload.get("user_count"),
        }
    except HTTPError as exc:
        return {"status": f"http_{exc.code}"}
    except Exception as exc:  # pragma: no cover
        return {"status": "error", "message": str(exc)}


def _check_database_connectivity(database_url: str) -> str:
    if database_url.startswith("sqlite:///"):
        path = database_url.removeprefix("sqlite:///")
        with sqlite3.connect(path) as conn:
            conn.execute("SELECT 1")
        return "ok"
    if database_url.startswith(("postgresql://", "postgres://")):
        if psycopg is None:
            return "psycopg_missing"
        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return "ok"
    return "unsupported"


def _check_schema(database_url: str) -> dict:
    required_columns = {
        "bars_1m": {"ts", "trading_day", "symbol", "instrument_key", "contract_month", "strike_price", "call_put", "session", "open", "high", "low", "close", "volume", "open_interest", "up_ticks", "down_ticks", "source", "build_source"},
        "bars_1d": {"ts", "trading_day", "symbol", "instrument_key", "contract_month", "strike_price", "call_put", "session", "open", "high", "low", "close", "volume", "open_interest", "up_ticks", "down_ticks", "source", "build_source"},
        "raw_ticks": {"ts", "trading_day", "symbol", "instrument_key", "contract_month", "strike_price", "call_put", "session", "price", "size", "tick_direction", "total_volume", "bid_side_total_vol", "ask_side_total_vol", "source", "payload_json"},
        "minute_force_features_1m": {"ts", "symbol", "instrument_key", "contract_month", "strike_price", "call_put", "run_id", "close", "volume", "up_ticks", "down_ticks", "tick_total", "net_tick_count", "tick_bias_ratio", "volume_per_tick", "force_score"},
        "live_run_metadata": {"run_id", "provider", "mode", "started_at", "session_scope", "topic_count", "symbols_json", "codes_json", "option_root", "underlying_future_symbol", "expiry_count", "atm_window", "call_put", "reference_price", "status"},
        "sync_state": {"source", "symbol", "timeframe", "session_scope", "cursor_ts", "updated_at"},
    }
    if database_url.startswith("sqlite:///"):
        path = database_url.removeprefix("sqlite:///")
        with sqlite3.connect(path) as conn:
            return {table: _sqlite_table_has_columns(conn, table, columns) for table, columns in required_columns.items()}
    if database_url.startswith(("postgresql://", "postgres://")) and psycopg is not None:
        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                return {table: _postgres_table_has_columns(cur, table, columns) for table, columns in required_columns.items()}
    return {"status": "unsupported"}


def _check_symbol_data(database_url: str, symbol: str, timeframe: str) -> dict:
    table = "bars_1m" if timeframe == "1m" else "bars_1d"
    if database_url.startswith("sqlite:///"):
        path = database_url.removeprefix("sqlite:///")
        with sqlite3.connect(path) as conn:
            count = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE symbol = ?", (symbol,)).fetchone()[0]
            trading_days = conn.execute(f"SELECT COUNT(DISTINCT trading_day) FROM {table} WHERE symbol = ?", (symbol,)).fetchone()[0]
        return {"count": count, "trading_days": trading_days}
    if database_url.startswith(("postgresql://", "postgres://")) and psycopg is not None:
        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*), COUNT(DISTINCT trading_day) FROM {table} WHERE symbol = %s", (symbol,))
                count, trading_days = cur.fetchone()
        return {"count": count, "trading_days": trading_days}
    return {"status": "unsupported"}


def _latest_bar_ts(database_url: str, symbol: str, timeframe: str) -> str | None:
    table = "bars_1m" if timeframe == "1m" else "bars_1d"
    if database_url.startswith("sqlite:///"):
        path = database_url.removeprefix("sqlite:///")
        with sqlite3.connect(path) as conn:
            row = conn.execute(f"SELECT MAX(ts) FROM {table} WHERE symbol = ?", (symbol,)).fetchone()
        return row[0] if row and row[0] else None
    if database_url.startswith(("postgresql://", "postgres://")) and psycopg is not None:
        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT MAX(ts) FROM {table} WHERE symbol = %s", (symbol,))
                row = cur.fetchone()
        return str(row[0]) if row and row[0] else None
    return None


def _latest_trading_day(database_url: str, symbol: str, timeframe: str) -> str | None:
    table = "bars_1m" if timeframe == "1m" else "bars_1d"
    if database_url.startswith("sqlite:///"):
        path = database_url.removeprefix("sqlite:///")
        with sqlite3.connect(path) as conn:
            row = conn.execute(f"SELECT MAX(trading_day) FROM {table} WHERE symbol = ?", (symbol,)).fetchone()
        return row[0] if row and row[0] else None
    if database_url.startswith(("postgresql://", "postgres://")) and psycopg is not None:
        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT MAX(trading_day) FROM {table} WHERE symbol = %s", (symbol,))
                row = cur.fetchone()
        return str(row[0]) if row and row[0] else None
    return None


def _sync_cursor(database_url: str, symbol: str, timeframe: str) -> dict:
    if database_url.startswith("sqlite:///"):
        path = database_url.removeprefix("sqlite:///")
        with sqlite3.connect(path) as conn:
            row = conn.execute(
                """
                SELECT cursor_ts, updated_at
                FROM sync_state
                WHERE source = ? AND symbol = ? AND timeframe = ? AND session_scope = ?
                """,
                ("finmind", symbol, timeframe, "day_and_night"),
            ).fetchone()
        if not row:
            return {"cursor_ts": None, "updated_at": None}
        return {"cursor_ts": row[0], "updated_at": row[1]}
    if database_url.startswith(("postgresql://", "postgres://")) and psycopg is not None:
        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT cursor_ts, updated_at
                    FROM sync_state
                    WHERE source = %s AND symbol = %s AND timeframe = %s AND session_scope = %s
                    """,
                    ("finmind", symbol, timeframe, "day_and_night"),
                )
                row = cur.fetchone()
        if not row:
            return {"cursor_ts": None, "updated_at": None}
        return {"cursor_ts": str(row[0]) if row[0] else None, "updated_at": str(row[1]) if row[1] else None}
    return {"cursor_ts": None, "updated_at": None}


def _sqlite_table_has_columns(conn: sqlite3.Connection, table: str, required: set[str]) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    columns = {row[1] for row in rows}
    return required.issubset(columns)


def _postgres_table_has_columns(cur, table: str, required: set[str]) -> bool:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = %s
        """,
        (table,),
    )
    columns = {row[0] for row in cur.fetchall()}
    return required.issubset(columns)


if __name__ == "__main__":
    main()
