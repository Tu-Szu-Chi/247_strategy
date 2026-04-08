from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Iterable

from qt_platform.domain import Bar
from qt_platform.storage.base import BarRepository

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None


class PostgresBarStore(BarRepository):
    def __init__(self, dsn: str) -> None:
        if psycopg is None:
            raise RuntimeError("psycopg is required for PostgreSQL/TimescaleDB storage.")
        self.dsn = dsn
        self._ensure_schema()

    def upsert_bars(self, timeframe: str, bars: Iterable[Bar]) -> int:
        rows = [self._bar_to_row(bar) for bar in bars]
        if not rows:
            return 0
        table = _table_name(timeframe)
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    f"""
                    INSERT INTO {table} (
                        ts, symbol, contract_month, session, open, high, low, close, volume, open_interest, source
                    ) VALUES (
                        %(ts)s, %(symbol)s, %(contract_month)s, %(session)s, %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s, %(open_interest)s, %(source)s
                    )
                    ON CONFLICT (ts, symbol, contract_month, session) DO UPDATE SET
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume,
                        open_interest = EXCLUDED.open_interest,
                        source = EXCLUDED.source
                    """,
                    rows,
                )
        return len(rows)

    def list_bars(self, timeframe: str, symbol: str, start: datetime, end: datetime) -> list[Bar]:
        table = _table_name(timeframe)
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT ts, symbol, contract_month, session, open, high, low, close, volume, open_interest, source
                    FROM {table}
                    WHERE symbol = %s AND ts >= %s AND ts <= %s
                    ORDER BY ts
                    """,
                    (symbol, _utc(start), _utc(end)),
                )
                rows = cur.fetchall()
        return [self._row_to_bar(row) for row in rows]

    def latest_bar_ts(self, timeframe: str, symbol: str) -> datetime | None:
        table = _table_name(timeframe)
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT MAX(ts) FROM {table} WHERE symbol = %s", (symbol,))
                row = cur.fetchone()
        if not row or row[0] is None:
            return None
        return _as_naive_utc(row[0])

    def update_sync_cursor(
        self,
        source: str,
        symbol: str,
        timeframe: str,
        session_scope: str,
        cursor_ts: datetime | None,
    ) -> None:
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO sync_state (source, symbol, timeframe, session_scope, cursor_ts, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (source, symbol, timeframe, session_scope) DO UPDATE SET
                        cursor_ts = EXCLUDED.cursor_ts,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        source,
                        symbol,
                        timeframe,
                        session_scope,
                        _utc(cursor_ts) if cursor_ts else None,
                        datetime.now(timezone.utc),
                    ),
                )

    def get_sync_cursor(
        self,
        source: str,
        symbol: str,
        timeframe: str,
        session_scope: str,
    ) -> datetime | None:
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT cursor_ts
                    FROM sync_state
                    WHERE source = %s AND symbol = %s AND timeframe = %s AND session_scope = %s
                    """,
                    (source, symbol, timeframe, session_scope),
                )
                row = cur.fetchone()
        if not row or row[0] is None:
            return None
        return _as_naive_utc(row[0])

    def _ensure_schema(self) -> None:
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS bars_1m (
                        ts TIMESTAMPTZ NOT NULL,
                        symbol TEXT NOT NULL,
                        contract_month TEXT NOT NULL,
                        session TEXT NOT NULL,
                        open DOUBLE PRECISION NOT NULL,
                        high DOUBLE PRECISION NOT NULL,
                        low DOUBLE PRECISION NOT NULL,
                        close DOUBLE PRECISION NOT NULL,
                        volume DOUBLE PRECISION NOT NULL,
                        open_interest DOUBLE PRECISION,
                        source TEXT NOT NULL,
                        PRIMARY KEY (ts, symbol, contract_month, session)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS bars_1d (
                        ts TIMESTAMPTZ NOT NULL,
                        symbol TEXT NOT NULL,
                        contract_month TEXT NOT NULL,
                        session TEXT NOT NULL,
                        open DOUBLE PRECISION NOT NULL,
                        high DOUBLE PRECISION NOT NULL,
                        low DOUBLE PRECISION NOT NULL,
                        close DOUBLE PRECISION NOT NULL,
                        volume DOUBLE PRECISION NOT NULL,
                        open_interest DOUBLE PRECISION,
                        source TEXT NOT NULL,
                        PRIMARY KEY (ts, symbol, contract_month, session)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS sync_state (
                        source TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        timeframe TEXT NOT NULL,
                        session_scope TEXT NOT NULL,
                        cursor_ts TIMESTAMPTZ,
                        updated_at TIMESTAMPTZ NOT NULL,
                        PRIMARY KEY (source, symbol, timeframe, session_scope)
                    )
                    """
                )
                cur.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb')"
                )
                if cur.fetchone()[0]:
                    cur.execute("SELECT create_hypertable('bars_1m', 'ts', if_not_exists => TRUE)")
                    cur.execute("SELECT create_hypertable('bars_1d', 'ts', if_not_exists => TRUE)")

    @staticmethod
    def _bar_to_row(bar: Bar) -> dict:
        row = asdict(bar)
        row["ts"] = _utc(bar.ts)
        return row

    @staticmethod
    def _row_to_bar(row: tuple) -> Bar:
        return Bar(
            ts=_as_naive_utc(row[0]),
            symbol=row[1],
            contract_month=row[2],
            session=row[3],
            open=float(row[4]),
            high=float(row[5]),
            low=float(row[6]),
            close=float(row[7]),
            volume=float(row[8]),
            open_interest=float(row[9]) if row[9] is not None else None,
            source=row[10],
        )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _as_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _table_name(timeframe: str) -> str:
    mapping = {
        "1m": "bars_1m",
        "1d": "bars_1d",
    }
    if timeframe not in mapping:
        raise ValueError(f"Unsupported timeframe for storage: {timeframe}")
    return mapping[timeframe]
