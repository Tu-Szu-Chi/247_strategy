from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date, datetime, timedelta
from urllib.error import HTTPError
from urllib.request import Request, urlopen

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None

from qt_platform.backtest.engine import BacktestConfig, run_backtest
from qt_platform.contracts import (
    is_continuous_symbol,
    resolve_mtx_monthly_contract,
    root_symbol_for,
    select_symbol_view,
)
from qt_platform.maintenance.service import MaintenanceService
from qt_platform.providers.finmind import FinMindAdapter
from qt_platform.reporting.performance import write_html_report
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
    elif args.command == "plan-sync":
        _plan_sync(args, settings)
    elif args.command == "sync-registry":
        _sync_registry(args, settings)
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
        "bars_1m": {"ts", "trading_day", "symbol", "instrument_key", "contract_month", "strike_price", "call_put", "session", "open", "high", "low", "close", "volume", "open_interest", "source", "build_source"},
        "bars_1d": {"ts", "trading_day", "symbol", "instrument_key", "contract_month", "strike_price", "call_put", "session", "open", "high", "low", "close", "volume", "open_interest", "source", "build_source"},
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
