from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from datetime import date, datetime, timedelta
from math import ceil
from pathlib import Path
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
from qt_platform.history_sync import build_history_entries, sync_history_days
from qt_platform.live.recorder import LiveRecordResult, LiveRecorderService
from qt_platform.live.shioaji_provider import ShioajiLiveProvider
from qt_platform.option_power import OptionPowerReplayService, OptionPowerRuntimeService
from qt_platform.contracts import (
    is_continuous_symbol,
    resolve_mtx_monthly_contract,
    root_symbol_for,
    select_symbol_view,
)
from qt_platform.maintenance.service import MaintenanceService
from qt_platform.providers.finmind import FinMindAdapter
from qt_platform.reporting.performance import write_backtest_report_bundle
from qt_platform.session import (
    is_in_activation_scope,
    is_in_session_scope,
    next_activation_start,
    next_session_start,
)
from qt_platform.settings import Settings, load_settings
from qt_platform.storage.factory import build_bar_repository
from qt_platform.strategies.sma_cross import SmaCrossStrategy
from qt_platform.symbol_registry import load_symbol_registry
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
    option_minute_features.add_argument("--underlying-future-symbol", default="MXFR1")
    option_minute_features.add_argument("--limit", type=int, default=20)
    option_minute_features.add_argument("--run-id")

    import_csv_parser = subparsers.add_parser("import-csv-folder")
    import_csv_parser.add_argument("--database-url")
    import_csv_parser.add_argument("--folder", required=True)
    import_csv_parser.add_argument("--pattern", default="*.csv")
    import_csv_parser.add_argument("--source", default="broker_csv")
    import_csv_parser.add_argument("--build-source", default="csv_1m_import")
    import_csv_parser.add_argument("--chunk-size", type=int, default=5000)

    runtime = subparsers.add_parser("runtime")
    runtime.add_argument("--database-url")
    runtime.add_argument("--registry")
    runtime.add_argument("--expiry-count", type=int, default=2)
    runtime.add_argument("--atm-window", type=int, default=20)
    runtime.add_argument("--underlying-future-symbol", default="MXFR1")
    runtime.add_argument("--call-put", default="both")
    runtime.add_argument("--max-events", type=int)
    runtime.add_argument("--batch-size", type=int, default=500)
    runtime.add_argument("--idle-timeout-seconds", type=float, default=30.0)
    runtime.add_argument("--simulation", action="store_true")
    runtime.add_argument("--session-scope", default="day_and_night")
    runtime.add_argument("--log-file", default="logs/runtime.log")

    history_sync = subparsers.add_parser("history-sync")
    history_sync.add_argument("--database-url")
    history_sync.add_argument("--registry")
    history_sync.add_argument("--start-date", required=True)
    history_sync.add_argument("--sync-time", default="15:05")
    history_sync.add_argument("--session-scope", default="day_and_night")
    history_sync.add_argument("--run-forever", action="store_true")
    history_sync.add_argument("--log-file", default="logs/history-sync.log")

    serve_option_power = subparsers.add_parser("serve-option-power")
    serve_option_power.add_argument("--database-url")
    serve_option_power.add_argument("--provider", default="shioaji")
    serve_option_power.add_argument("--option-root", default="AUTO")
    serve_option_power.add_argument("--expiry-count", type=int, default=2)
    serve_option_power.add_argument("--atm-window", type=int, default=20)
    serve_option_power.add_argument("--underlying-future-symbol", default="MXFR1")
    serve_option_power.add_argument("--call-put", default="both")
    serve_option_power.add_argument("--batch-size", type=int, default=500)
    serve_option_power.add_argument("--idle-timeout-seconds", type=float, default=30.0)
    serve_option_power.add_argument("--simulation", action="store_true")
    serve_option_power.add_argument("--session-scope", default="day_and_night")
    serve_option_power.add_argument("--host", default="127.0.0.1")
    serve_option_power.add_argument("--port", type=int, default=8000)
    serve_option_power.add_argument("--snapshot-interval-seconds", type=float, default=10.0)
    serve_option_power.add_argument("--ready-timeout-seconds", type=float, default=15.0)
    serve_option_power.add_argument("--replay-underlying-symbol", default="MTX")
    serve_option_power.add_argument("--log-file", default="logs/serve-option-power.log")

    serve_option_power_replay = subparsers.add_parser("serve-option-power-replay")
    serve_option_power_replay.add_argument("--database-url")
    serve_option_power_replay.add_argument("--option-root", default="AUTO")
    serve_option_power_replay.add_argument("--expiry-count", type=int, default=2)
    serve_option_power_replay.add_argument("--underlying-symbol", default="MTX")
    serve_option_power_replay.add_argument("--host", default="127.0.0.1")
    serve_option_power_replay.add_argument("--port", type=int, default=8000)
    serve_option_power_replay.add_argument("--snapshot-interval-seconds", type=float, default=10.0)
    serve_option_power_replay.add_argument("--start", required=True)
    serve_option_power_replay.add_argument("--end", required=True)
    serve_option_power_replay.add_argument("--log-file", default="logs/serve-option-power-replay.log")

    benchmark_replay = subparsers.add_parser("benchmark-replay")
    benchmark_replay.add_argument("--database-url")
    benchmark_replay.add_argument("--start", required=True)
    benchmark_replay.add_argument("--end", required=True)
    benchmark_replay.add_argument("--symbol", default="MTX")
    benchmark_replay.add_argument("--option-root", default="AUTO")
    benchmark_replay.add_argument("--expiry-count", type=int, default=2)
    benchmark_replay.add_argument("--snapshot-interval-seconds", type=float, default=10.0)
    benchmark_replay.add_argument("--window-bars", type=int, default=200)
    benchmark_replay.add_argument("--runs", type=int, default=5)
    benchmark_replay.add_argument("--report-dir", default="reports/benchmarks")

    resolve_contract = subparsers.add_parser("resolve-contract")
    resolve_contract.add_argument("--symbol", default="MTX")
    resolve_contract.add_argument("--date", required=True)

    args = parser.parse_args()
    settings = load_settings(args.config)
    if args.command == "scan-gaps":
        _scan_gaps(args, settings)
    elif args.command == "backtest":
        _backtest(args, settings)
    elif args.command == "doctor":
        _doctor(args, settings)
    elif args.command == "minute-features":
        _minute_features(args, settings)
    elif args.command == "option-minute-features":
        _option_minute_features(args, settings)
    elif args.command == "import-csv-folder":
        _import_csv_folder(args, settings)
    elif args.command == "runtime":
        _runtime(args, settings)
    elif args.command == "history-sync":
        _history_sync(args, settings)
    elif args.command == "serve-option-power":
        _serve_option_power(args, settings)
    elif args.command == "serve-option-power-replay":
        _serve_option_power_replay(args, settings)
    elif args.command == "benchmark-replay":
        _benchmark_replay(args, settings)
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
    result = run_backtest(
        bars=bars,
        strategy=strategy,
        config=BacktestConfig(),
    )
    report, report_json = write_backtest_report_bundle(
        result,
        _report_dir(args, settings),
        f"{args.symbol}-backtest",
    )
    print(f"ending_cash={result.ending_cash:.2f}")
    print(f"report={report}")
    print(f"report_json={report_json}")


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


def _runtime_universe_from_registry(registry_path: str) -> tuple[list[str], set[str]]:
    registry_entries = load_symbol_registry(registry_path)
    stock_symbols = sorted(
        {
            entry.symbol
            for entry in registry_entries
            if entry.instrument_type == "stock"
        }
    )
    exact_symbols = sorted({_live_symbol_for_registry_future("MTX"), *stock_symbols})
    return exact_symbols, {"TXO"}


def _live_symbol_for_registry_future(symbol: str) -> str:
    mapping = {
        "MTX": "MXFR1",
        "MXF": "MXFR1",
        "TX": "MXFR1",
        "TXF": "MXFR1",
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


def _runtime(args: argparse.Namespace, settings: Settings) -> None:
    _runtime_daemon(args, settings) if args.max_events is None else print(
        json.dumps(_run_runtime_cycle(args, settings).to_dict(), ensure_ascii=False, indent=2)
    )


def _history_sync(args: argparse.Namespace, settings: Settings) -> None:
    if args.run_forever:
        _history_sync_daemon(args, settings)
        return
    start_date = date.fromisoformat(args.start_date)
    end_date = _history_sync_end_date(settings)
    if end_date < start_date:
        print(
            json.dumps(
                {
                    "status": "noop",
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "message": "No historical trading days are available yet for sync.",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    result = _run_history_sync_once(args, settings, start_date, end_date)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


def _runtime_daemon(args: argparse.Namespace, settings: Settings) -> None:
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

        result = _run_runtime_cycle(args, settings)
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

        idle_seconds = max(args.idle_timeout_seconds, 5.0)
        time.sleep(idle_seconds)


def _run_runtime_cycle(args: argparse.Namespace, settings: Settings) -> LiveRecordResult:
    store = build_bar_repository(_database_url(args, settings))
    provider = ShioajiLiveProvider(
        settings=settings.shioaji,
        idle_timeout_seconds=args.idle_timeout_seconds,
        simulation=args.simulation,
    )
    service = LiveRecorderService(provider=provider, store=store)
    run_id = _new_live_run_id()
    registry_path = args.registry or settings.sync.registry_path
    exact_symbols, option_roots = _runtime_universe_from_registry(registry_path)
    provider.connect()
    _emit_runtime_status(
        {"status": "connected", "provider": "shioaji", "simulation": args.simulation, "run_id": run_id},
        args.log_file,
    )
    try:
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
            mode="runtime",
            started_at=datetime.now(),
            session_scope=args.session_scope,
            topic_count=len(contracts),
            symbols_json=symbols_json,
            codes_json=codes_json,
            option_root=",".join(extra_metadata.get("resolved_option_roots", sorted(option_roots))),
            underlying_future_symbol=args.underlying_future_symbol,
            expiry_count=args.expiry_count,
            atm_window=args.atm_window,
            call_put=args.call_put,
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
            args.log_file,
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
        provider.close()
        raise
    finally:
        stop_reason = provider.stop_reason()
        provider.close()

    final_status = stop_reason or "completed"
    store.create_live_run(LiveRunMetadata(**{**metadata.__dict__, "status": final_status}))
    return LiveRecordResult(
        run_id=run_id,
        ticks_appended=result.ticks_appended,
        bars_upserted=result.bars_upserted,
        first_tick_ts=result.first_tick_ts,
        last_tick_ts=result.last_tick_ts,
        stop_reason=stop_reason,
        usage_status=(usage_after or usage_before).to_dict() if (usage_after or usage_before) else None,
    )


def _history_sync_daemon(args: argparse.Namespace, settings: Settings) -> None:
    sync_time = _parse_sync_time(args.sync_time)
    current_start = date.fromisoformat(args.start_date)
    while True:
        end_date = _history_sync_end_date(settings)
        if end_date >= current_start:
            result = _run_history_sync_once(args, settings, current_start, end_date)
            _emit_runtime_status(result.to_dict(), args.log_file)
            current_start = end_date + timedelta(days=1)
        wake_at = _next_history_sync_at(datetime.now(ZoneInfo(settings.app.timezone)), args.sync_time, settings)
        _emit_runtime_status(
            {
                "status": "waiting_for_history_sync",
                "sync_time": sync_time.strftime("%H:%M"),
                "wake_at": wake_at.isoformat(),
            },
            args.log_file,
        )
        _sleep_until(wake_at)


def _run_history_sync_once(
    args: argparse.Namespace,
    settings: Settings,
    start_date: date,
    end_date: date,
):
    store = build_bar_repository(_database_url(args, settings))
    provider = _provider(settings)
    registry_path = args.registry or settings.sync.registry_path
    entries = build_history_entries(load_symbol_registry(registry_path))

    def progress_callback(payload: dict) -> None:
        _emit_runtime_status(payload, args.log_file)

    _emit_runtime_status(
        {
            "status": "history_sync_started",
            "registry_path": registry_path,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "timeframes": ["1d", "1m"],
        },
        args.log_file,
    )
    result = sync_history_days(
        store=store,
        provider=provider,
        entries=entries,
        start_date=start_date,
        end_date=end_date,
        timeframes=["1d", "1m"],
        session_scope=args.session_scope,
        progress_callback=progress_callback,
    )
    _emit_runtime_status(
        {
            "status": "history_sync_completed",
            "registry_path": registry_path,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "processed": result.processed,
            "synced": result.synced,
            "skipped": result.skipped,
            "failed": result.failed,
        },
        args.log_file,
    )
    return result


def _history_sync_end_date(settings: Settings) -> date:
    today = datetime.now(ZoneInfo(settings.app.timezone)).date()
    return today - timedelta(days=1)


def _next_history_sync_at(now: datetime, sync_time: str, settings: Settings) -> datetime:
    timezone = ZoneInfo(settings.app.timezone)
    local_now = now.astimezone(timezone)
    parsed_time = _parse_sync_time(sync_time)
    candidate = local_now.replace(
        hour=parsed_time.hour,
        minute=parsed_time.minute,
        second=0,
        microsecond=0,
    )
    if candidate <= local_now:
        candidate += timedelta(days=1)
    return candidate


def _parse_sync_time(value: str):
    return datetime.strptime(value, "%H:%M").time()


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
    replay = OptionPowerReplayService(
        store=store,
        option_root=args.option_root,
        expiry_count=args.expiry_count,
        underlying_symbol=args.replay_underlying_symbol,
        snapshot_interval_seconds=args.snapshot_interval_seconds,
    )
    run_id = _new_live_run_id()
    runtime.start(run_id=run_id)
    if not runtime.wait_until_ready(timeout=args.ready_timeout_seconds):
        raise RuntimeError("Option power runtime did not become ready within timeout.")
    if runtime.status in {"error", "completed", "paused_for_usage_limit"}:
        raise RuntimeError(runtime.error_message or f"Option power runtime failed with status={runtime.status}.")

    app = build_option_power_app(runtime_service=runtime, replay_service=replay)
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


def _serve_option_power_replay(args: argparse.Namespace, settings: Settings) -> None:
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "uvicorn is required for serve-option-power-replay. Install with: pip install -e .[web]"
        ) from exc

    store = build_bar_repository(_database_url(args, settings))
    replay = OptionPowerReplayService(
        store=store,
        option_root=args.option_root,
        expiry_count=args.expiry_count,
        underlying_symbol=args.underlying_symbol,
        snapshot_interval_seconds=args.snapshot_interval_seconds,
    )
    metadata = replay.create_session(
        start=datetime.fromisoformat(args.start),
        end=datetime.fromisoformat(args.end),
        set_as_default=True,
    )
    app = build_option_power_app(replay_service=replay)
    _emit_runtime_status(
        {
            "status": "replay_web_ready",
            "host": args.host,
            "port": args.port,
            "url": f"http://{args.host}:{args.port}/",
            "research_url": f"http://{args.host}:{args.port}/research",
            "replay_session_id": metadata["session_id"],
            "snapshot_count": metadata["snapshot_count"],
            "selected_option_roots": metadata["selected_option_roots"],
            "underlying_symbol": metadata["underlying_symbol"],
            "start": metadata["start"],
            "end": metadata["end"],
        },
        args.log_file,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info", access_log=False)


def _benchmark_replay(args: argparse.Namespace, settings: Settings) -> None:
    store = build_bar_repository(_database_url(args, settings))
    replay = OptionPowerReplayService(
        store=store,
        option_root=args.option_root,
        expiry_count=args.expiry_count,
        underlying_symbol=args.symbol,
        snapshot_interval_seconds=args.snapshot_interval_seconds,
    )
    start = datetime.fromisoformat(args.start)
    end = datetime.fromisoformat(args.end)
    window_end = min(end, start + timedelta(minutes=max(args.window_bars - 1, 0)))
    series_names = [
        "pressure_index",
        "raw_pressure",
        "pressure_index_weighted",
        "raw_pressure_weighted",
        "regime_state",
        "trend_score",
        "adx_14",
        "session_cvd",
        "iv_skew",
    ]

    create_started = time.perf_counter()
    metadata = replay.create_session(start=start, end=end, set_as_default=True)
    session_create_latency = time.perf_counter() - create_started

    compute_started = time.perf_counter()
    replay.wait_until_ready(metadata["session_id"], timeout=max(1.0, (end - start).total_seconds()))
    background_compute_total_time = time.perf_counter() - compute_started
    progress = replay.get_progress(metadata["session_id"]) or {}

    bars_latencies: list[float] = []
    series_latencies: list[float] = []
    snapshot_latencies: list[float] = []
    json_encode_latencies: list[float] = []
    payload_bytes: list[int] = []

    for _ in range(max(args.runs, 1)):
        started = time.perf_counter()
        bars = replay.get_bars(metadata["session_id"], start=start, end=window_end, interval="1m") or []
        bars_latencies.append(time.perf_counter() - started)

        started = time.perf_counter()
        series_payload = replay.get_series_payload(
            metadata["session_id"],
            series_names,
            start=start,
            end=window_end,
            interval="1m",
        ) or {"series": {}}
        series_latencies.append(time.perf_counter() - started)

        snapshot_at = start + (window_end - start) / 2
        started = time.perf_counter()
        snapshot = replay.get_snapshot_at(metadata["session_id"], snapshot_at) or {}
        snapshot_latencies.append(time.perf_counter() - started)

        started = time.perf_counter()
        encoded = json.dumps(
            {"bars": bars, "series": series_payload, "snapshot": snapshot},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        json_encode_latencies.append(time.perf_counter() - started)
        payload_bytes.append(len(encoded))

    report = {
        "generated_at": datetime.now().isoformat(),
        "command": "benchmark-replay",
        "session_id": metadata["session_id"],
        "symbol": args.symbol,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "window_bars": args.window_bars,
        "runs": max(args.runs, 1),
        "session_create_latency": session_create_latency,
        "background_compute_total_time": background_compute_total_time,
        "bars_api_p50": _percentile(bars_latencies, 0.50),
        "bars_api_p95": _percentile(bars_latencies, 0.95),
        "series_api_p50": _percentile(series_latencies, 0.50),
        "series_api_p95": _percentile(series_latencies, 0.95),
        "snapshot_at_p50": _percentile(snapshot_latencies, 0.50),
        "snapshot_at_p95": _percentile(snapshot_latencies, 0.95),
        "checkpoint_hit_rate": 1.0 if int(progress.get("checkpoint_count") or 0) > 0 else 0.0,
        "checkpoint_count": progress.get("checkpoint_count", 0),
        "db_query_time": None,
        "json_encode_time_p50": _percentile(json_encode_latencies, 0.50),
        "json_encode_time_p95": _percentile(json_encode_latencies, 0.95),
        "payload_bytes_p50": _percentile([float(value) for value in payload_bytes], 0.50),
        "payload_bytes_p95": _percentile([float(value) for value in payload_bytes], 0.95),
        "compute_status": progress.get("compute_status"),
        "progress_ratio": progress.get("progress_ratio"),
    }

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"replay-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report_path": str(report_path), **report}, ensure_ascii=False, indent=2))


def _resolve_contract(args: argparse.Namespace) -> None:
    if args.symbol != "MTX":
        raise ValueError("Only MTX monthly contract resolution is implemented in v1.")
    resolution = resolve_mtx_monthly_contract(date.fromisoformat(args.date))
    print(json.dumps(resolution.__dict__, ensure_ascii=False, indent=2, default=str))


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, ceil(quantile * len(ordered)) - 1))
    return ordered[index]


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
