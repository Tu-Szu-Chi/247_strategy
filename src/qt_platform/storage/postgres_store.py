from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timezone
from typing import Iterable

from qt_platform.domain import Bar
from qt_platform.session import trading_day_for
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
                        ts, trading_day, symbol, instrument_key, contract_month, strike_price, call_put, session, open, high, low, close, volume, open_interest, source, build_source
                    ) VALUES (
                        %(ts)s, %(trading_day)s, %(symbol)s, %(instrument_key)s, %(contract_month)s, %(strike_price)s, %(call_put)s, %(session)s, %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s, %(open_interest)s, %(source)s, %(build_source)s
                    )
                    ON CONFLICT (ts, symbol, contract_month, session) DO UPDATE SET
                        instrument_key = EXCLUDED.instrument_key,
                        strike_price = EXCLUDED.strike_price,
                        call_put = EXCLUDED.call_put,
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume,
                        open_interest = EXCLUDED.open_interest,
                        source = EXCLUDED.source,
                        build_source = EXCLUDED.build_source
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
                    SELECT ts, trading_day, symbol, contract_month, session, open, high, low, close, volume, open_interest, source, instrument_key, strike_price, call_put, build_source
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

    def list_trading_days(
        self,
        timeframe: str,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> list[date]:
        table = _table_name(timeframe)
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT DISTINCT trading_day
                    FROM {table}
                    WHERE symbol = %s AND trading_day >= %s AND trading_day <= %s
                    ORDER BY trading_day
                    """,
                    (symbol, start_date, end_date),
                )
                rows = cur.fetchall()
        return [row[0] for row in rows]

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
                        trading_day DATE NOT NULL,
                        symbol TEXT NOT NULL,
                        instrument_key TEXT,
                        contract_month TEXT NOT NULL,
                        strike_price DOUBLE PRECISION,
                        call_put TEXT,
                        session TEXT NOT NULL,
                        open DOUBLE PRECISION NOT NULL,
                        high DOUBLE PRECISION NOT NULL,
                        low DOUBLE PRECISION NOT NULL,
                        close DOUBLE PRECISION NOT NULL,
                        volume DOUBLE PRECISION NOT NULL,
                        open_interest DOUBLE PRECISION,
                        source TEXT NOT NULL,
                        build_source TEXT NOT NULL DEFAULT 'historical',
                        PRIMARY KEY (ts, symbol, contract_month, session)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS bars_1d (
                        ts TIMESTAMPTZ NOT NULL,
                        trading_day DATE NOT NULL,
                        symbol TEXT NOT NULL,
                        instrument_key TEXT,
                        contract_month TEXT NOT NULL,
                        strike_price DOUBLE PRECISION,
                        call_put TEXT,
                        session TEXT NOT NULL,
                        open DOUBLE PRECISION NOT NULL,
                        high DOUBLE PRECISION NOT NULL,
                        low DOUBLE PRECISION NOT NULL,
                        close DOUBLE PRECISION NOT NULL,
                        volume DOUBLE PRECISION NOT NULL,
                        open_interest DOUBLE PRECISION,
                        source TEXT NOT NULL,
                        build_source TEXT NOT NULL DEFAULT 'historical',
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
                self._migrate_schema(cur)

    def _migrate_schema(self, cur) -> None:
        cur.execute(
            """
            ALTER TABLE bars_1m
            ADD COLUMN IF NOT EXISTS trading_day DATE
            """
        )
        cur.execute("ALTER TABLE bars_1m ADD COLUMN IF NOT EXISTS instrument_key TEXT")
        cur.execute("ALTER TABLE bars_1m ADD COLUMN IF NOT EXISTS strike_price DOUBLE PRECISION")
        cur.execute("ALTER TABLE bars_1m ADD COLUMN IF NOT EXISTS call_put TEXT")
        cur.execute("ALTER TABLE bars_1m ADD COLUMN IF NOT EXISTS build_source TEXT")
        cur.execute(
            """
            ALTER TABLE bars_1d
            ADD COLUMN IF NOT EXISTS trading_day DATE
            """
        )
        cur.execute("ALTER TABLE bars_1d ADD COLUMN IF NOT EXISTS instrument_key TEXT")
        cur.execute("ALTER TABLE bars_1d ADD COLUMN IF NOT EXISTS strike_price DOUBLE PRECISION")
        cur.execute("ALTER TABLE bars_1d ADD COLUMN IF NOT EXISTS call_put TEXT")
        cur.execute("ALTER TABLE bars_1d ADD COLUMN IF NOT EXISTS build_source TEXT")

        cur.execute("SELECT ts, session FROM bars_1m WHERE trading_day IS NULL")
        bars_1m_rows = cur.fetchall()
        for ts, session in bars_1m_rows:
            trading_day = trading_day_for(_as_naive_utc(ts)) if session == "night" else _as_naive_utc(ts).date()
            cur.execute(
                "UPDATE bars_1m SET trading_day = %s WHERE ts = %s AND session = %s",
                (trading_day, ts, session),
            )

        cur.execute("SELECT ts FROM bars_1d WHERE trading_day IS NULL")
        bars_1d_rows = cur.fetchall()
        for (ts,) in bars_1d_rows:
            cur.execute(
                "UPDATE bars_1d SET trading_day = %s WHERE ts = %s",
                (_as_naive_utc(ts).date(), ts),
            )

        cur.execute("ALTER TABLE bars_1m ALTER COLUMN trading_day SET NOT NULL")
        cur.execute("ALTER TABLE bars_1d ALTER COLUMN trading_day SET NOT NULL")
        cur.execute("UPDATE bars_1m SET build_source = 'historical' WHERE build_source IS NULL")
        cur.execute("UPDATE bars_1d SET build_source = 'historical' WHERE build_source IS NULL")
        cur.execute("ALTER TABLE bars_1m ALTER COLUMN build_source SET NOT NULL")
        cur.execute("ALTER TABLE bars_1d ALTER COLUMN build_source SET NOT NULL")

    @staticmethod
    def _bar_to_row(bar: Bar) -> dict:
        row = asdict(bar)
        row["ts"] = _utc(bar.ts)
        row["trading_day"] = bar.trading_day
        return row

    @staticmethod
    def _row_to_bar(row: tuple) -> Bar:
        return Bar(
            ts=_as_naive_utc(row[0]),
            trading_day=row[1],
            symbol=row[2],
            contract_month=row[3],
            session=row[4],
            open=float(row[5]),
            high=float(row[6]),
            low=float(row[7]),
            close=float(row[8]),
            volume=float(row[9]),
            open_interest=float(row[10]) if row[10] is not None else None,
            source=row[11],
            instrument_key=row[12],
            strike_price=float(row[13]) if row[13] is not None else None,
            call_put=row[14],
            build_source=row[15],
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
