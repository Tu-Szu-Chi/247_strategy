from __future__ import annotations

import sqlite3
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from qt_platform.domain import Bar
from qt_platform.storage.base import BarRepository


SCHEMA = """
CREATE TABLE IF NOT EXISTS bars_1m (
    ts TEXT NOT NULL,
    trading_day TEXT NOT NULL,
    symbol TEXT NOT NULL,
    instrument_key TEXT,
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
    PRIMARY KEY (ts, symbol, contract_month, session)
);

CREATE TABLE IF NOT EXISTS bars_1d (
    ts TEXT NOT NULL,
    trading_day TEXT NOT NULL,
    symbol TEXT NOT NULL,
    instrument_key TEXT,
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
    PRIMARY KEY (ts, symbol, contract_month, session)
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
                ON CONFLICT(ts, symbol, contract_month, session) DO UPDATE SET
                    instrument_key=excluded.instrument_key,
                    strike_price=excluded.strike_price,
                    call_put=excluded.call_put,
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

    @staticmethod
    def _bar_to_row(bar: Bar) -> dict:
        row = asdict(bar)
        row["ts"] = bar.ts.isoformat()
        row["trading_day"] = bar.trading_day.isoformat()
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
