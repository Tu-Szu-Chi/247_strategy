from __future__ import annotations

import sqlite3
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from qt_platform.domain import Bar
from qt_platform.session import trading_day_for
from qt_platform.storage.base import BarRepository


SCHEMA = """
CREATE TABLE IF NOT EXISTS bars_1m (
    ts TEXT NOT NULL,
    trading_day TEXT NOT NULL,
    symbol TEXT NOT NULL,
    instrument_key TEXT NOT NULL,
    contract_month TEXT NOT NULL,
    strike_price REAL,
    call_put TEXT,
    session TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    open_interest REAL,
    source TEXT NOT NULL,
    build_source TEXT NOT NULL DEFAULT 'historical',
    PRIMARY KEY (ts, instrument_key, contract_month, session)
);

CREATE TABLE IF NOT EXISTS bars_1d (
    ts TEXT NOT NULL,
    trading_day TEXT NOT NULL,
    symbol TEXT NOT NULL,
    instrument_key TEXT NOT NULL,
    contract_month TEXT NOT NULL,
    strike_price REAL,
    call_put TEXT,
    session TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    open_interest REAL,
    source TEXT NOT NULL,
    build_source TEXT NOT NULL DEFAULT 'historical',
    PRIMARY KEY (ts, instrument_key, contract_month, session)
);

CREATE TABLE IF NOT EXISTS sync_state (
    source TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    session_scope TEXT NOT NULL,
    cursor_ts TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (source, symbol, timeframe, session_scope)
);
"""


class SQLiteBarStore(BarRepository):
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._ensure_schema()

    def upsert_bars(self, timeframe: str, bars: Iterable[Bar]) -> int:
        rows = [self._bar_to_row(bar) for bar in bars]
        if not rows:
            return 0
        table = _table_name(timeframe)
        with sqlite3.connect(self.path) as conn:
            conn.executemany(
                f"""
                INSERT INTO {table} (
                    ts, trading_day, symbol, instrument_key, contract_month, strike_price, call_put, session, open, high, low, close, volume, open_interest, source, build_source
                ) VALUES (
                    :ts, :trading_day, :symbol, :instrument_key, :contract_month, :strike_price, :call_put, :session, :open, :high, :low, :close, :volume, :open_interest, :source, :build_source
                )
                ON CONFLICT(ts, instrument_key, contract_month, session) DO UPDATE SET
                    strike_price=excluded.strike_price,
                    call_put=excluded.call_put,
                    symbol=excluded.symbol,
                    open=excluded.open,
                    high=excluded.high,
                    low=excluded.low,
                    close=excluded.close,
                    volume=excluded.volume,
                    open_interest=excluded.open_interest,
                    source=excluded.source,
                    build_source=excluded.build_source
                """,
                rows,
            )
        return len(rows)

    def list_bars(self, timeframe: str, symbol: str, start: datetime, end: datetime) -> list[Bar]:
        table = _table_name(timeframe)
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(
                f"""
                SELECT ts, trading_day, symbol, instrument_key, contract_month, strike_price, call_put, session, open, high, low, close, volume, open_interest, source, build_source
                FROM {table}
                WHERE symbol = ? AND ts >= ? AND ts <= ?
                ORDER BY ts
                """,
                (symbol, start.isoformat(), end.isoformat()),
            )
            rows = cursor.fetchall()
        return [self._row_to_bar(row) for row in rows]

    def latest_bar_ts(self, timeframe: str, symbol: str) -> datetime | None:
        table = _table_name(timeframe)
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(
                f"SELECT MAX(ts) FROM {table} WHERE symbol = ?",
                (symbol,),
            )
            row = cursor.fetchone()
        if not row or row[0] is None:
            return None
        return datetime.fromisoformat(row[0])

    def list_trading_days(
        self,
        timeframe: str,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> list[date]:
        table = _table_name(timeframe)
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(
                f"""
                SELECT DISTINCT trading_day
                FROM {table}
                WHERE symbol = ? AND trading_day >= ? AND trading_day <= ?
                ORDER BY trading_day
                """,
                (symbol, start_date.isoformat(), end_date.isoformat()),
            )
            rows = cursor.fetchall()
        return [datetime.fromisoformat(f"{row[0]}T00:00:00").date() for row in rows]

    def update_sync_cursor(
        self,
        source: str,
        symbol: str,
        timeframe: str,
        session_scope: str,
        cursor_ts: datetime | None,
    ) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                INSERT INTO sync_state (source, symbol, timeframe, session_scope, cursor_ts, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, symbol, timeframe, session_scope) DO UPDATE SET
                    cursor_ts=excluded.cursor_ts,
                    updated_at=excluded.updated_at
                """,
                (
                    source,
                    symbol,
                    timeframe,
                    session_scope,
                    cursor_ts.isoformat() if cursor_ts else None,
                    datetime.utcnow().isoformat(),
                ),
            )

    def get_sync_cursor(
        self,
        source: str,
        symbol: str,
        timeframe: str,
        session_scope: str,
    ) -> datetime | None:
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(
                """
                SELECT cursor_ts
                FROM sync_state
                WHERE source = ? AND symbol = ? AND timeframe = ? AND session_scope = ?
                """,
                (source, symbol, timeframe, session_scope),
            )
            row = cursor.fetchone()
        if not row or row[0] is None:
            return None
        return datetime.fromisoformat(row[0])

    def _ensure_schema(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.executescript(SCHEMA)
            for table in ("bars_1m", "bars_1d"):
                for ddl in (
                    f"ALTER TABLE {table} ADD COLUMN trading_day TEXT",
                    f"ALTER TABLE {table} ADD COLUMN instrument_key TEXT",
                    f"ALTER TABLE {table} ADD COLUMN strike_price REAL",
                    f"ALTER TABLE {table} ADD COLUMN call_put TEXT",
                    f"ALTER TABLE {table} ADD COLUMN build_source TEXT NOT NULL DEFAULT 'historical'",
                ):
                    try:
                        conn.execute(ddl)
                    except sqlite3.OperationalError as exc:
                        if "duplicate column name" not in str(exc).lower():
                            raise
                _backfill_trading_day(conn, table)
                conn.execute(f"UPDATE {table} SET instrument_key = symbol WHERE instrument_key IS NULL")
                conn.execute(f"UPDATE {table} SET build_source = 'historical' WHERE build_source IS NULL")
                if not _has_primary_key(conn, table, ("ts", "instrument_key", "contract_month", "session")):
                    _rebuild_table_with_primary_key(conn, table)

    @staticmethod
    def _bar_to_row(bar: Bar) -> dict:
        row = asdict(bar)
        row["ts"] = bar.ts.isoformat()
        row["trading_day"] = bar.trading_day.isoformat()
        row["instrument_key"] = bar.instrument_key or bar.symbol
        return row

    @staticmethod
    def _row_to_bar(row: tuple) -> Bar:
        return Bar(
            ts=datetime.fromisoformat(row[0]),
            trading_day=datetime.fromisoformat(f"{row[1]}T00:00:00").date(),
            symbol=row[2],
            instrument_key=row[3],
            contract_month=row[4],
            strike_price=float(row[5]) if row[5] is not None else None,
            call_put=row[6],
            session=row[7],
            open=float(row[8]),
            high=float(row[9]),
            low=float(row[10]),
            close=float(row[11]),
            volume=float(row[12]),
            open_interest=float(row[13]) if row[13] is not None else None,
            source=row[14],
            build_source=row[15],
        )


def _table_name(timeframe: str) -> str:
    mapping = {
        "1m": "bars_1m",
        "1d": "bars_1d",
    }
    if timeframe not in mapping:
        raise ValueError(f"Unsupported timeframe for storage: {timeframe}")
    return mapping[timeframe]


def _has_primary_key(conn: sqlite3.Connection, table: str, expected_columns: tuple[str, ...]) -> bool:
    cursor = conn.execute(f"PRAGMA table_info({table})")
    pk_columns = []
    for row in cursor.fetchall():
        pk_position = row[5]
        if pk_position:
            pk_columns.append((pk_position, row[1]))
    ordered = tuple(name for _, name in sorted(pk_columns))
    return ordered == expected_columns


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def _select_expr(columns: set[str], name: str, fallback: str | None = None) -> str:
    if name in columns:
        return name
    if fallback is not None:
        return fallback
    raise RuntimeError(f"Column {name} does not exist and no fallback was provided.")


def _backfill_trading_day(conn: sqlite3.Connection, table: str) -> None:
    columns = _column_names(conn, table)
    if "trading_day" not in columns:
        return
    if table == "bars_1m":
        cursor = conn.execute(f"SELECT ts, session FROM {table} WHERE trading_day IS NULL")
        for ts, session in cursor.fetchall():
            dt = datetime.fromisoformat(ts)
            trading_day = trading_day_for(dt) if session == "night" else dt.date()
            conn.execute(
                f"UPDATE {table} SET trading_day = ? WHERE ts = ? AND session = ?",
                (trading_day.isoformat(), ts, session),
            )
        return
    conn.execute(f"UPDATE {table} SET trading_day = substr(ts, 1, 10) WHERE trading_day IS NULL")


def _rebuild_table_with_primary_key(conn: sqlite3.Connection, table: str) -> None:
    temp_table = f"{table}__new"
    columns = _column_names(conn, table)
    conn.execute(f"DROP TABLE IF EXISTS {temp_table}")
    conn.execute(
        f"""
        CREATE TABLE {temp_table} (
            ts TEXT NOT NULL,
            trading_day TEXT NOT NULL,
            symbol TEXT NOT NULL,
            instrument_key TEXT NOT NULL,
            contract_month TEXT NOT NULL,
            strike_price REAL,
            call_put TEXT,
            session TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            open_interest REAL,
            source TEXT NOT NULL,
            build_source TEXT NOT NULL DEFAULT 'historical',
            PRIMARY KEY (ts, instrument_key, contract_month, session)
        )
        """
    )
    conn.execute(
        f"""
        INSERT INTO {temp_table} (
            ts, trading_day, symbol, instrument_key, contract_month, strike_price, call_put, session, open, high, low, close, volume, open_interest, source, build_source
        )
        SELECT
            {_select_expr(columns, 'ts')},
            {_select_expr(columns, 'trading_day', "substr(ts, 1, 10)")},
            {_select_expr(columns, 'symbol')},
            {_select_expr(columns, 'instrument_key', "symbol")},
            {_select_expr(columns, 'contract_month')},
            {_select_expr(columns, 'strike_price', "NULL")},
            {_select_expr(columns, 'call_put', "NULL")},
            {_select_expr(columns, 'session')},
            {_select_expr(columns, 'open')},
            {_select_expr(columns, 'high')},
            {_select_expr(columns, 'low')},
            {_select_expr(columns, 'close')},
            {_select_expr(columns, 'volume')},
            {_select_expr(columns, 'open_interest', "NULL")},
            {_select_expr(columns, 'source')},
            {_select_expr(columns, 'build_source', "'historical'")}
        FROM {table}
        """
    )
    conn.execute(f"DROP TABLE {table}")
    conn.execute(f"ALTER TABLE {temp_table} RENAME TO {table}")
