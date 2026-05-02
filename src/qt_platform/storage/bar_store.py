from __future__ import annotations

import sqlite3
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from time import perf_counter
from typing import Iterable

from qt_platform.domain import Bar, CanonicalTick, LiveRunMetadata
from qt_platform.features import MinuteForceFeatures
from qt_platform.trading_calendar import trading_day_for
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
    up_ticks REAL,
    down_ticks REAL,
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
    up_ticks REAL,
    down_ticks REAL,
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

CREATE TABLE IF NOT EXISTS raw_ticks (
    ts TEXT NOT NULL,
    trading_day TEXT NOT NULL,
    symbol TEXT NOT NULL,
    instrument_key TEXT NOT NULL,
    contract_month TEXT NOT NULL,
    strike_price REAL,
    call_put TEXT,
    session TEXT NOT NULL,
    price REAL NOT NULL,
    size REAL NOT NULL,
    tick_direction TEXT,
    total_volume REAL,
    bid_side_total_vol REAL,
    ask_side_total_vol REAL,
    source TEXT NOT NULL,
    payload_json TEXT,
    PRIMARY KEY (ts, instrument_key, price, size, source)
);

CREATE TABLE IF NOT EXISTS minute_force_features_1m (
    ts TEXT NOT NULL,
    symbol TEXT NOT NULL,
    instrument_key TEXT NOT NULL,
    contract_month TEXT NOT NULL,
    strike_price REAL,
    call_put TEXT,
    run_id TEXT NOT NULL DEFAULT '',
    close REAL NOT NULL,
    volume REAL NOT NULL,
    up_ticks REAL,
    down_ticks REAL,
    tick_total REAL NOT NULL,
    net_tick_count REAL NOT NULL,
    tick_bias_ratio REAL NOT NULL,
    volume_per_tick REAL,
    force_score REAL NOT NULL,
    PRIMARY KEY (ts, instrument_key, contract_month, run_id)
);

CREATE TABLE IF NOT EXISTS live_run_metadata (
    run_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    mode TEXT NOT NULL,
    started_at TEXT NOT NULL,
    session_scope TEXT NOT NULL,
    topic_count INTEGER NOT NULL,
    symbols_json TEXT NOT NULL,
    codes_json TEXT,
    option_root TEXT,
    underlying_future_symbol TEXT,
    expiry_count INTEGER,
    atm_window INTEGER,
    call_put TEXT,
    reference_price REAL,
    status TEXT NOT NULL
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
                    ts, trading_day, symbol, instrument_key, contract_month, strike_price, call_put, session, open, high, low, close, volume, open_interest, up_ticks, down_ticks, source, build_source
                ) VALUES (
                    :ts, :trading_day, :symbol, :instrument_key, :contract_month, :strike_price, :call_put, :session, :open, :high, :low, :close, :volume, :open_interest, :up_ticks, :down_ticks, :source, :build_source
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
                    up_ticks=excluded.up_ticks,
                    down_ticks=excluded.down_ticks,
                    source=excluded.source,
                    build_source=excluded.build_source
                """,
                rows,
            )
        return len(rows)

    def list_bars(self, timeframe: str, symbol: str, start: datetime, end: datetime) -> list[Bar]:
        rows, _ = self.list_bars_profiled(timeframe, symbol, start, end)
        return rows

    def list_bars_profiled(
        self,
        timeframe: str,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> tuple[list[Bar], dict]:
        table = _table_name(timeframe)
        query_started = perf_counter()
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(
                f"""
                SELECT ts, trading_day, symbol, instrument_key, contract_month, strike_price, call_put, session, open, high, low, close, volume, open_interest, up_ticks, down_ticks, source, build_source
                FROM {table}
                WHERE symbol = ? AND ts >= ? AND ts <= ?
                ORDER BY ts
                """,
                (symbol, start.isoformat(), end.isoformat()),
            )
            rows = cursor.fetchall()
        db_fetch_seconds = perf_counter() - query_started
        decode_started = perf_counter()
        bars = [self._row_to_bar(row) for row in rows]
        decode_seconds = perf_counter() - decode_started
        return bars, {
            "db_fetch_seconds": db_fetch_seconds,
            "decode_seconds": decode_seconds,
            "row_count": len(rows),
        }

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

    def bar_time_bounds(self, timeframe: str, symbol: str) -> tuple[datetime, datetime] | None:
        table = _table_name(timeframe)
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(
                f"SELECT MIN(ts), MAX(ts) FROM {table} WHERE symbol = ?",
                (symbol,),
            )
            row = cursor.fetchone()
        if not row or row[0] is None or row[1] is None:
            return None
        return datetime.fromisoformat(row[0]), datetime.fromisoformat(row[1])

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

    def append_ticks(self, ticks: Iterable[CanonicalTick]) -> int:
        rows = [self._tick_to_row(tick) for tick in ticks]
        if not rows:
            return 0
        with sqlite3.connect(self.path) as conn:
            conn.executemany(
                """
                INSERT INTO raw_ticks (
                    ts, trading_day, symbol, instrument_key, contract_month, strike_price, call_put, session, price, size, tick_direction, total_volume, bid_side_total_vol, ask_side_total_vol, source, payload_json
                ) VALUES (
                    :ts, :trading_day, :symbol, :instrument_key, :contract_month, :strike_price, :call_put, :session, :price, :size, :tick_direction, :total_volume, :bid_side_total_vol, :ask_side_total_vol, :source, :payload_json
                )
                ON CONFLICT(ts, instrument_key, price, size, source) DO UPDATE SET
                    trading_day=excluded.trading_day,
                    symbol=excluded.symbol,
                    contract_month=excluded.contract_month,
                    strike_price=excluded.strike_price,
                    call_put=excluded.call_put,
                    session=excluded.session,
                    tick_direction=excluded.tick_direction,
                    total_volume=excluded.total_volume,
                    bid_side_total_vol=excluded.bid_side_total_vol,
                    ask_side_total_vol=excluded.ask_side_total_vol,
                    payload_json=excluded.payload_json
                """,
                rows,
            )
        return len(rows)

    def list_ticks(self, symbol: str, start: datetime, end: datetime) -> list[CanonicalTick]:
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(
                """
                SELECT ts, trading_day, symbol, instrument_key, contract_month, strike_price, call_put, session, price, size, tick_direction, total_volume, bid_side_total_vol, ask_side_total_vol, source, payload_json
                FROM raw_ticks
                WHERE symbol = ? AND ts >= ? AND ts <= ?
                ORDER BY ts
                """,
                (symbol, start.isoformat(), end.isoformat()),
            )
            rows = cursor.fetchall()
        return [self._row_to_tick(row) for row in rows]

    def list_ticks_for_symbols(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
    ) -> list[CanonicalTick]:
        rows, _ = self.list_ticks_for_symbols_profiled(symbols, start, end)
        return rows

    def list_ticks_for_symbols_profiled(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
    ) -> tuple[list[CanonicalTick], dict]:
        if not symbols:
            return [], {"db_fetch_seconds": 0.0, "decode_seconds": 0.0, "row_count": 0}
        placeholders = ",".join("?" for _ in symbols)
        query_started = perf_counter()
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(
                f"""
                SELECT ts, trading_day, symbol, instrument_key, contract_month, strike_price, call_put, session, price, size, tick_direction, total_volume, bid_side_total_vol, ask_side_total_vol, source, payload_json
                FROM raw_ticks
                WHERE symbol IN ({placeholders}) AND ts >= ? AND ts <= ?
                ORDER BY ts, instrument_key, price, size, source
                """,
                [*symbols, start.isoformat(), end.isoformat()],
            )
            rows = cursor.fetchall()
        db_fetch_seconds = perf_counter() - query_started
        decode_started = perf_counter()
        ticks = [self._row_to_tick(row) for row in rows]
        decode_seconds = perf_counter() - decode_started
        return ticks, {
            "db_fetch_seconds": db_fetch_seconds,
            "decode_seconds": decode_seconds,
            "row_count": len(rows),
        }

    def list_ticks_for_symbols_replay_profiled(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
    ) -> tuple[list[CanonicalTick], dict]:
        if not symbols:
            return [], {"db_fetch_seconds": 0.0, "decode_seconds": 0.0, "row_count": 0}
        placeholders = ",".join("?" for _ in symbols)
        query_started = perf_counter()
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(
                f"""
                SELECT ts, trading_day, symbol, instrument_key, contract_month, strike_price, call_put, session, price, size, tick_direction, source
                FROM raw_ticks
                WHERE symbol IN ({placeholders}) AND ts >= ? AND ts <= ?
                ORDER BY ts, instrument_key, price, size, source
                """,
                [*symbols, start.isoformat(), end.isoformat()],
            )
            rows = cursor.fetchall()
        db_fetch_seconds = perf_counter() - query_started
        decode_started = perf_counter()
        ticks = [self._row_to_replay_tick(row) for row in rows]
        decode_seconds = perf_counter() - decode_started
        return ticks, {
            "db_fetch_seconds": db_fetch_seconds,
            "decode_seconds": decode_seconds,
            "row_count": len(rows),
        }

    def list_tick_symbol_stats(
        self,
        symbols: list[str],
        start: datetime,
        end: datetime,
    ) -> list[dict]:
        if not symbols:
            return []
        placeholders = ",".join("?" for _ in symbols)
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(
                f"""
                SELECT symbol, MIN(contract_month), COUNT(*)
                FROM raw_ticks
                WHERE symbol IN ({placeholders})
                  AND ts >= ?
                  AND ts <= ?
                  AND strike_price IS NOT NULL
                  AND call_put IS NOT NULL
                GROUP BY symbol
                """,
                [*symbols, start.isoformat(), end.isoformat()],
            )
            rows = cursor.fetchall()
        return [
            {
                "symbol": row[0],
                "first_contract_month": row[1] or "999999",
                "tick_count": int(row[2]),
            }
            for row in rows
        ]

    def upsert_minute_force_features(self, features: Iterable[MinuteForceFeatures]) -> int:
        rows = [self._feature_to_row(feature) for feature in features]
        if not rows:
            return 0
        with sqlite3.connect(self.path) as conn:
            conn.executemany(
                """
                INSERT INTO minute_force_features_1m (
                    ts, symbol, instrument_key, contract_month, strike_price, call_put, run_id, close, volume, up_ticks, down_ticks,
                    tick_total, net_tick_count, tick_bias_ratio, volume_per_tick, force_score
                ) VALUES (
                    :ts, :symbol, :instrument_key, :contract_month, :strike_price, :call_put, :run_id, :close, :volume, :up_ticks, :down_ticks,
                    :tick_total, :net_tick_count, :tick_bias_ratio, :volume_per_tick, :force_score
                )
                ON CONFLICT(ts, instrument_key, contract_month, run_id) DO UPDATE SET
                    symbol=excluded.symbol,
                    strike_price=excluded.strike_price,
                    call_put=excluded.call_put,
                    close=excluded.close,
                    volume=excluded.volume,
                    up_ticks=excluded.up_ticks,
                    down_ticks=excluded.down_ticks,
                    tick_total=excluded.tick_total,
                    net_tick_count=excluded.net_tick_count,
                    tick_bias_ratio=excluded.tick_bias_ratio,
                    volume_per_tick=excluded.volume_per_tick,
                    force_score=excluded.force_score
                """,
                rows,
            )
        return len(rows)

    def list_minute_force_features(
        self,
        symbol: str | None,
        start: datetime,
        end: datetime,
        run_id: str | None = None,
        symbols: list[str] | None = None,
        instrument_keys: list[str] | None = None,
        contract_month: str | None = None,
        strike_price: float | None = None,
        call_put: str | None = None,
    ) -> list[MinuteForceFeatures]:
        query = """
            SELECT ts, symbol, instrument_key, contract_month, strike_price, call_put, run_id, close, volume, up_ticks, down_ticks,
                   tick_total, net_tick_count, tick_bias_ratio, volume_per_tick, force_score
            FROM minute_force_features_1m
            WHERE ts >= ? AND ts <= ?
        """
        params: list = [start.isoformat(), end.isoformat()]
        if symbols:
            placeholders = ",".join("?" for _ in symbols)
            query += f" AND symbol IN ({placeholders})"
            params.extend(symbols)
        elif symbol is not None:
            query += " AND symbol = ?"
            params.append(symbol)
        if run_id is not None:
            query += " AND run_id = ?"
            params.append(run_id)
        if instrument_keys:
            placeholders = ",".join("?" for _ in instrument_keys)
            query += f" AND instrument_key IN ({placeholders})"
            params.extend(instrument_keys)
        if contract_month is not None:
            query += " AND contract_month = ?"
            params.append(contract_month)
        if strike_price is not None:
            query += " AND strike_price = ?"
            params.append(strike_price)
        if call_put is not None:
            query += " AND call_put = ?"
            params.append(call_put)
        query += " ORDER BY ts"
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
        return [self._row_to_feature(row) for row in rows]

    def create_live_run(self, metadata: LiveRunMetadata) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                INSERT INTO live_run_metadata (
                    run_id, provider, mode, started_at, session_scope, topic_count, symbols_json, codes_json,
                    option_root, underlying_future_symbol, expiry_count, atm_window, call_put, reference_price, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    provider=excluded.provider,
                    mode=excluded.mode,
                    started_at=excluded.started_at,
                    session_scope=excluded.session_scope,
                    topic_count=excluded.topic_count,
                    symbols_json=excluded.symbols_json,
                    codes_json=excluded.codes_json,
                    option_root=excluded.option_root,
                    underlying_future_symbol=excluded.underlying_future_symbol,
                    expiry_count=excluded.expiry_count,
                    atm_window=excluded.atm_window,
                    call_put=excluded.call_put,
                    reference_price=excluded.reference_price,
                    status=excluded.status
                """,
                (
                    metadata.run_id,
                    metadata.provider,
                    metadata.mode,
                    metadata.started_at.isoformat(),
                    metadata.session_scope,
                    metadata.topic_count,
                    metadata.symbols_json,
                    metadata.codes_json,
                    metadata.option_root,
                    metadata.underlying_future_symbol,
                    metadata.expiry_count,
                    metadata.atm_window,
                    metadata.call_put,
                    metadata.reference_price,
                    metadata.status,
                ),
            )

    def get_live_run(self, run_id: str) -> LiveRunMetadata | None:
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(
                """
                SELECT run_id, provider, mode, started_at, session_scope, topic_count, symbols_json, codes_json,
                       option_root, underlying_future_symbol, expiry_count, atm_window, call_put, reference_price, status
                FROM live_run_metadata
                WHERE run_id = ?
                """,
                (run_id,),
            )
            row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_live_run(row)

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
                    f"ALTER TABLE {table} ADD COLUMN up_ticks REAL",
                    f"ALTER TABLE {table} ADD COLUMN down_ticks REAL",
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
            for ddl in (
                "ALTER TABLE raw_ticks ADD COLUMN trading_day TEXT",
                "ALTER TABLE raw_ticks ADD COLUMN instrument_key TEXT",
                "ALTER TABLE raw_ticks ADD COLUMN contract_month TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE raw_ticks ADD COLUMN strike_price REAL",
                "ALTER TABLE raw_ticks ADD COLUMN call_put TEXT",
                "ALTER TABLE raw_ticks ADD COLUMN session TEXT",
                "ALTER TABLE raw_ticks ADD COLUMN tick_direction TEXT",
                "ALTER TABLE raw_ticks ADD COLUMN total_volume REAL",
                "ALTER TABLE raw_ticks ADD COLUMN bid_side_total_vol REAL",
                "ALTER TABLE raw_ticks ADD COLUMN ask_side_total_vol REAL",
                "ALTER TABLE raw_ticks ADD COLUMN payload_json TEXT",
            ):
                try:
                    conn.execute(ddl)
                except sqlite3.OperationalError as exc:
                    if "duplicate column name" not in str(exc).lower():
                        raise
            conn.execute("UPDATE raw_ticks SET instrument_key = symbol WHERE instrument_key IS NULL")
            conn.execute("UPDATE raw_ticks SET contract_month = '' WHERE contract_month IS NULL")
            conn.execute("UPDATE raw_ticks SET session = 'unknown' WHERE session IS NULL")
            conn.execute("UPDATE raw_ticks SET trading_day = substr(ts, 1, 10) WHERE trading_day IS NULL")
            for ddl in (
                "ALTER TABLE minute_force_features_1m ADD COLUMN run_id TEXT",
                "ALTER TABLE minute_force_features_1m ADD COLUMN strike_price REAL",
                "ALTER TABLE minute_force_features_1m ADD COLUMN call_put TEXT",
            ):
                try:
                    conn.execute(ddl)
                except sqlite3.OperationalError as exc:
                    if "duplicate column name" not in str(exc).lower():
                        raise
            _ensure_indexes(conn)

    @staticmethod
    def _bar_to_row(bar: Bar) -> dict:
        row = asdict(bar)
        row["ts"] = bar.ts.isoformat()
        row["trading_day"] = bar.trading_day.isoformat()
        row["instrument_key"] = bar.instrument_key or bar.symbol
        return row

    @staticmethod
    def _tick_to_row(tick: CanonicalTick) -> dict:
        return {
            "ts": tick.ts.isoformat(),
            "trading_day": tick.trading_day.isoformat(),
            "symbol": tick.symbol,
            "instrument_key": tick.instrument_key or tick.symbol,
            "contract_month": tick.contract_month,
            "strike_price": tick.strike_price,
            "call_put": tick.call_put,
            "session": tick.session,
            "price": tick.price,
            "size": tick.size,
            "tick_direction": tick.tick_direction,
            "total_volume": tick.total_volume,
            "bid_side_total_vol": tick.bid_side_total_vol,
            "ask_side_total_vol": tick.ask_side_total_vol,
            "source": tick.source,
            "payload_json": tick.payload_json,
        }

    @staticmethod
    def _feature_to_row(feature: MinuteForceFeatures) -> dict:
        return {
            "ts": feature.ts,
            "symbol": feature.symbol,
            "instrument_key": feature.instrument_key or feature.symbol,
            "contract_month": feature.contract_month,
            "strike_price": feature.strike_price,
            "call_put": feature.call_put,
            "run_id": feature.run_id or "",
            "close": feature.close,
            "volume": feature.volume,
            "up_ticks": feature.up_ticks,
            "down_ticks": feature.down_ticks,
            "tick_total": feature.tick_total,
            "net_tick_count": feature.net_tick_count,
            "tick_bias_ratio": feature.tick_bias_ratio,
            "volume_per_tick": feature.volume_per_tick,
            "force_score": feature.force_score,
        }

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
            up_ticks=float(row[14]) if row[14] is not None else None,
            down_ticks=float(row[15]) if row[15] is not None else None,
            source=row[16],
            build_source=row[17],
        )

    @staticmethod
    def _row_to_tick(row: tuple) -> CanonicalTick:
        return CanonicalTick(
            ts=datetime.fromisoformat(row[0]),
            trading_day=datetime.fromisoformat(f"{row[1]}T00:00:00").date(),
            symbol=row[2],
            instrument_key=row[3],
            contract_month=row[4],
            strike_price=float(row[5]) if row[5] is not None else None,
            call_put=row[6],
            session=row[7],
            price=float(row[8]),
            size=float(row[9]),
            tick_direction=row[10],
            total_volume=float(row[11]) if row[11] is not None else None,
            bid_side_total_vol=float(row[12]) if row[12] is not None else None,
            ask_side_total_vol=float(row[13]) if row[13] is not None else None,
            source=row[14],
            payload_json=row[15],
        )

    @staticmethod
    def _row_to_replay_tick(row: tuple) -> CanonicalTick:
        return CanonicalTick(
            ts=datetime.fromisoformat(row[0]),
            trading_day=datetime.fromisoformat(f"{row[1]}T00:00:00").date(),
            symbol=row[2],
            instrument_key=row[3],
            contract_month=row[4],
            strike_price=float(row[5]) if row[5] is not None else None,
            call_put=row[6],
            session=row[7],
            price=float(row[8]),
            size=float(row[9]),
            tick_direction=row[10],
            source=row[11],
        )

    @staticmethod
    def _row_to_feature(row: tuple) -> MinuteForceFeatures:
        return MinuteForceFeatures(
            ts=row[0],
            symbol=row[1],
            instrument_key=row[2],
            contract_month=row[3],
            strike_price=float(row[4]) if row[4] is not None else None,
            call_put=row[5],
            run_id=row[6],
            close=float(row[7]),
            volume=float(row[8]),
            up_ticks=float(row[9]) if row[9] is not None else None,
            down_ticks=float(row[10]) if row[10] is not None else None,
            tick_total=float(row[11]),
            net_tick_count=float(row[12]),
            tick_bias_ratio=float(row[13]),
            volume_per_tick=float(row[14]) if row[14] is not None else None,
            force_score=float(row[15]),
        )

    @staticmethod
    def _row_to_live_run(row: tuple) -> LiveRunMetadata:
        return LiveRunMetadata(
            run_id=row[0],
            provider=row[1],
            mode=row[2],
            started_at=datetime.fromisoformat(row[3]),
            session_scope=row[4],
            topic_count=int(row[5]),
            symbols_json=row[6],
            codes_json=row[7],
            option_root=row[8],
            underlying_future_symbol=row[9],
            expiry_count=int(row[10]) if row[10] is not None else None,
            atm_window=int(row[11]) if row[11] is not None else None,
            call_put=row[12],
            reference_price=float(row[13]) if row[13] is not None else None,
            status=row[14],
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


def _ensure_indexes(conn: sqlite3.Connection) -> None:
    for ddl in (
        "CREATE INDEX IF NOT EXISTS idx_bars_1m_symbol_ts ON bars_1m(symbol, ts)",
        "CREATE INDEX IF NOT EXISTS idx_bars_1d_symbol_ts ON bars_1d(symbol, ts)",
        "CREATE INDEX IF NOT EXISTS idx_raw_ticks_symbol_ts ON raw_ticks(symbol, ts)",
        "CREATE INDEX IF NOT EXISTS idx_minute_force_features_1m_symbol_ts ON minute_force_features_1m(symbol, ts)",
    ):
        conn.execute(ddl)


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
            up_ticks REAL,
            down_ticks REAL,
            source TEXT NOT NULL,
            build_source TEXT NOT NULL DEFAULT 'historical',
            PRIMARY KEY (ts, instrument_key, contract_month, session)
        )
        """
    )
    conn.execute(
        f"""
        INSERT INTO {temp_table} (
            ts, trading_day, symbol, instrument_key, contract_month, strike_price, call_put, session, open, high, low, close, volume, open_interest, up_ticks, down_ticks, source, build_source
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
            {_select_expr(columns, 'up_ticks', "NULL")},
            {_select_expr(columns, 'down_ticks', "NULL")},
            {_select_expr(columns, 'source')},
            {_select_expr(columns, 'build_source', "'historical'")}
        FROM {table}
        """
    )
    conn.execute(f"DROP TABLE {table}")
    conn.execute(f"ALTER TABLE {temp_table} RENAME TO {table}")
