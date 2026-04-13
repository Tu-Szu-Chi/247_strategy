from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from datetime import date, datetime, timedelta
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
from qt_platform.live.recorder import LiveRecordResult, LiveRecorderService
from qt_platform.live.shioaji_provider import ShioajiLiveProvider
from qt_platform.live.stub_provider import StubLiveProvider
from qt_platform.contracts import (
    is_continuous_symbol,
    resolve_mtx_monthly_contract,
    root_symbol_for,
    select_symbol_view,
)
from qt_platform.maintenance.service import MaintenanceService
from qt_platform.providers.finmind import FinMindAdapter
from qt_platform.reporting.performance import write_html_report
from qt_platform.session import is_in_session_scope, next_session_start
from qt_platform.settings import Settings, load_settings
from qt_platform.storage.factory import build_bar_repository
from qt_platform.strategies.sma_cross import SmaCrossStrategy
from qt_platform.symbol_registry import load_symbol_registry
from qt_platform.sync_executor import sync_registry
from qt_platform.sync_planner import plan_sync


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
    record_live.add_argument("--option-root")
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

    preview_option_universe = subparsers.add_parser("preview-option-universe")
    preview_option_universe.add_argument("--option-root", default="TXO")
    preview_option_universe.add_argument("--expiry-count", type=int, default=2)
    preview_option_universe.add_argument("--atm-window", type=int, default=20)
    preview_option_universe.add_argument("--underlying-future-symbol", default="TXFR1")
    preview_option_universe.add_argument("--call-put", default="both")

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
    elif args.command == "preview-option-universe":
        _preview_option_universe(args, settings)
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

    if args.run_id:
        metadata = store.get_live_run(args.run_id)
        if metadata is None:
            raise ValueError(f"run_id '{args.run_id}' was not found.")
        allowed_instrument_keys = set(json.loads(metadata.codes_json or "[]"))
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
            contracts, reference_price = provider.resolve_option_universe(
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
        resolver_payload = {
            "option_root": args.option_root,
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
        symbol="TXO",
        start=start,
        end=end,
        run_id=args.run_id,
        instrument_keys=sorted(allowed_instrument_keys) if allowed_instrument_keys else None,
        contract_month=args.contract_month,
        strike_price=args.strike_price,
        call_put=args.call_put if args.call_put in {"call", "put"} else None,
    )
    payload = {
        "symbol": "TXO",
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
    if args.symbols:
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
            contracts, reference_price = provider.resolve_option_universe(
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
                option_root=args.option_root,
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
                    "option_root": args.option_root,
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
        if not is_in_session_scope(now.replace(tzinfo=None), args.session_scope):
            wake_at = next_session_start(now.replace(tzinfo=None), args.session_scope).replace(tzinfo=timezone)
            _emit_runtime_status(
                {
                    "status": "waiting_for_session",
                    "now": now.isoformat(),
                    "wake_at": wake_at.isoformat(),
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
    print(json.dumps(payload, ensure_ascii=False, indent=2))
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
        contracts = provider.resolve_option_contracts(
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
        "expiry_count": args.expiry_count,
        "atm_window": args.atm_window,
        "underlying_future_symbol": args.underlying_future_symbol,
        "call_put": args.call_put,
        "count": len(contracts),
        "symbols": [getattr(contract, "symbol", None) for contract in contracts],
        "codes": [getattr(contract, "code", None) for contract in contracts],
        "usage_status": usage.to_dict() if usage else None,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


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
