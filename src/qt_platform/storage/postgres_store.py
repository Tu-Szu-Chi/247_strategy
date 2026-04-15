from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

from qt_platform.domain import Bar, CanonicalTick, LiveRunMetadata
from qt_platform.features import MinuteForceFeatures
from qt_platform.session import trading_day_for
from qt_platform.storage.base import BarRepository

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None


LOCAL_TIMEZONE = ZoneInfo("Asia/Taipei")


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
                        ts, trading_day, symbol, instrument_key, contract_month, strike_price, call_put, session, open, high, low, close, volume, open_interest, up_ticks, down_ticks, source, build_source
                    ) VALUES (
                        %(ts)s, %(trading_day)s, %(symbol)s, %(instrument_key)s, %(contract_month)s, %(strike_price)s, %(call_put)s, %(session)s, %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s, %(open_interest)s, %(up_ticks)s, %(down_ticks)s, %(source)s, %(build_source)s
                    )
                    ON CONFLICT (ts, instrument_key, contract_month, session) DO UPDATE SET
                        strike_price = EXCLUDED.strike_price,
                        call_put = EXCLUDED.call_put,
                        symbol = EXCLUDED.symbol,
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume,
                        open_interest = EXCLUDED.open_interest,
                        up_ticks = EXCLUDED.up_ticks,
                        down_ticks = EXCLUDED.down_ticks,
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
                    SELECT ts, trading_day, symbol, contract_month, session, open, high, low, close, volume, open_interest, up_ticks, down_ticks, source, instrument_key, strike_price, call_put, build_source
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
        return _as_naive_local(row[0])

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
        return _as_naive_local(row[0])

    def append_ticks(self, ticks: Iterable[CanonicalTick]) -> int:
        rows = [self._tick_to_row(tick) for tick in ticks]
        if not rows:
            return 0
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO raw_ticks (
                        ts, trading_day, symbol, instrument_key, contract_month, strike_price, call_put, session, price, size, tick_direction, total_volume, bid_side_total_vol, ask_side_total_vol, source, payload_json
                    ) VALUES (
                        %(ts)s, %(trading_day)s, %(symbol)s, %(instrument_key)s, %(contract_month)s, %(strike_price)s, %(call_put)s, %(session)s, %(price)s, %(size)s, %(tick_direction)s, %(total_volume)s, %(bid_side_total_vol)s, %(ask_side_total_vol)s, %(source)s, %(payload_json)s
                    )
                    ON CONFLICT (ts, instrument_key, price, size, source) DO UPDATE SET
                        trading_day = EXCLUDED.trading_day,
                        symbol = EXCLUDED.symbol,
                        contract_month = EXCLUDED.contract_month,
                        strike_price = EXCLUDED.strike_price,
                        call_put = EXCLUDED.call_put,
                        session = EXCLUDED.session,
                        tick_direction = EXCLUDED.tick_direction,
                        total_volume = EXCLUDED.total_volume,
                        bid_side_total_vol = EXCLUDED.bid_side_total_vol,
                        ask_side_total_vol = EXCLUDED.ask_side_total_vol,
                        payload_json = EXCLUDED.payload_json
                    """,
                    rows,
                )
        return len(rows)

    def list_ticks(self, symbol: str, start: datetime, end: datetime) -> list[CanonicalTick]:
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT ts, trading_day, symbol, instrument_key, contract_month, strike_price, call_put, session, price, size, tick_direction, total_volume, bid_side_total_vol, ask_side_total_vol, source, payload_json
                    FROM raw_ticks
                    WHERE symbol = %s AND ts >= %s AND ts <= %s
                    ORDER BY ts
                    """,
                    (symbol, _utc(start), _utc(end)),
                )
                rows = cur.fetchall()
        return [self._row_to_tick(row) for row in rows]

    def upsert_minute_force_features(self, features: Iterable[MinuteForceFeatures]) -> int:
        rows = [self._feature_to_row(feature) for feature in features]
        if not rows:
            return 0
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO minute_force_features_1m (
                        ts, symbol, instrument_key, contract_month, strike_price, call_put, run_id, close, volume, up_ticks, down_ticks,
                        tick_total, net_tick_count, tick_bias_ratio, volume_per_tick, force_score
                    ) VALUES (
                        %(ts)s, %(symbol)s, %(instrument_key)s, %(contract_month)s, %(strike_price)s, %(call_put)s, %(run_id)s, %(close)s, %(volume)s, %(up_ticks)s, %(down_ticks)s,
                        %(tick_total)s, %(net_tick_count)s, %(tick_bias_ratio)s, %(volume_per_tick)s, %(force_score)s
                    )
                    ON CONFLICT (ts, instrument_key, contract_month, run_id) DO UPDATE SET
                        symbol = EXCLUDED.symbol,
                        strike_price = EXCLUDED.strike_price,
                        call_put = EXCLUDED.call_put,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume,
                        up_ticks = EXCLUDED.up_ticks,
                        down_ticks = EXCLUDED.down_ticks,
                        tick_total = EXCLUDED.tick_total,
                        net_tick_count = EXCLUDED.net_tick_count,
                        tick_bias_ratio = EXCLUDED.tick_bias_ratio,
                        volume_per_tick = EXCLUDED.volume_per_tick,
                        force_score = EXCLUDED.force_score
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
            WHERE ts >= %s AND ts <= %s
        """
        params: list = [_utc(start), _utc(end)]
        if symbols:
            query += " AND symbol = ANY(%s)"
            params.append(symbols)
        elif symbol is not None:
            query += " AND symbol = %s"
            params.append(symbol)
        if run_id is not None:
            query += " AND run_id = %s"
            params.append(run_id)
        if instrument_keys:
            query += " AND instrument_key = ANY(%s)"
            params.append(instrument_keys)
        if contract_month is not None:
            query += " AND contract_month = %s"
            params.append(contract_month)
        if strike_price is not None:
            query += " AND strike_price = %s"
            params.append(strike_price)
        if call_put is not None:
            query += " AND call_put = %s"
            params.append(call_put)
        query += " ORDER BY ts"
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
        return [self._row_to_feature(row) for row in rows]

    def create_live_run(self, metadata: LiveRunMetadata) -> None:
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO live_run_metadata (
                        run_id, provider, mode, started_at, session_scope, topic_count, symbols_json, codes_json,
                        option_root, underlying_future_symbol, expiry_count, atm_window, call_put, reference_price, status
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (run_id) DO UPDATE SET
                        provider = EXCLUDED.provider,
                        mode = EXCLUDED.mode,
                        started_at = EXCLUDED.started_at,
                        session_scope = EXCLUDED.session_scope,
                        topic_count = EXCLUDED.topic_count,
                        symbols_json = EXCLUDED.symbols_json,
                        codes_json = EXCLUDED.codes_json,
                        option_root = EXCLUDED.option_root,
                        underlying_future_symbol = EXCLUDED.underlying_future_symbol,
                        expiry_count = EXCLUDED.expiry_count,
                        atm_window = EXCLUDED.atm_window,
                        call_put = EXCLUDED.call_put,
                        reference_price = EXCLUDED.reference_price,
                        status = EXCLUDED.status
                    """,
                    (
                        metadata.run_id,
                        metadata.provider,
                        metadata.mode,
                        _utc(metadata.started_at),
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
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT run_id, provider, mode, started_at, session_scope, topic_count, symbols_json, codes_json,
                           option_root, underlying_future_symbol, expiry_count, atm_window, call_put, reference_price, status
                    FROM live_run_metadata
                    WHERE run_id = %s
                    """,
                    (run_id,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._row_to_live_run(row)

    def _ensure_schema(self) -> None:
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS bars_1m (
                        ts TIMESTAMPTZ NOT NULL,
                        trading_day DATE NOT NULL,
                        symbol TEXT NOT NULL,
                        instrument_key TEXT NOT NULL,
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
                        up_ticks DOUBLE PRECISION,
                        down_ticks DOUBLE PRECISION,
                        source TEXT NOT NULL,
                        build_source TEXT NOT NULL DEFAULT 'historical',
                        PRIMARY KEY (ts, instrument_key, contract_month, session)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS bars_1d (
                        ts TIMESTAMPTZ NOT NULL,
                        trading_day DATE NOT NULL,
                        symbol TEXT NOT NULL,
                        instrument_key TEXT NOT NULL,
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
                        up_ticks DOUBLE PRECISION,
                        down_ticks DOUBLE PRECISION,
                        source TEXT NOT NULL,
                        build_source TEXT NOT NULL DEFAULT 'historical',
                        PRIMARY KEY (ts, instrument_key, contract_month, session)
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
                    """
                    CREATE TABLE IF NOT EXISTS raw_ticks (
                        ts TIMESTAMPTZ NOT NULL,
                        trading_day DATE NOT NULL,
                        symbol TEXT NOT NULL,
                        instrument_key TEXT NOT NULL,
                        contract_month TEXT NOT NULL,
                        strike_price DOUBLE PRECISION,
                        call_put TEXT,
                        session TEXT NOT NULL,
                        price DOUBLE PRECISION NOT NULL,
                        size DOUBLE PRECISION NOT NULL,
                        tick_direction TEXT,
                        total_volume DOUBLE PRECISION,
                        bid_side_total_vol DOUBLE PRECISION,
                        ask_side_total_vol DOUBLE PRECISION,
                        source TEXT NOT NULL,
                        payload_json TEXT,
                        PRIMARY KEY (ts, instrument_key, price, size, source)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS minute_force_features_1m (
                        ts TIMESTAMPTZ NOT NULL,
                        symbol TEXT NOT NULL,
                        instrument_key TEXT NOT NULL,
                        contract_month TEXT NOT NULL,
                        strike_price DOUBLE PRECISION,
                        call_put TEXT,
                        run_id TEXT NOT NULL DEFAULT '',
                        close DOUBLE PRECISION NOT NULL,
                        volume DOUBLE PRECISION NOT NULL,
                        up_ticks DOUBLE PRECISION,
                        down_ticks DOUBLE PRECISION,
                        tick_total DOUBLE PRECISION NOT NULL,
                        net_tick_count DOUBLE PRECISION NOT NULL,
                        tick_bias_ratio DOUBLE PRECISION NOT NULL,
                        volume_per_tick DOUBLE PRECISION,
                        force_score DOUBLE PRECISION NOT NULL,
                        PRIMARY KEY (ts, instrument_key, contract_month, run_id)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS live_run_metadata (
                        run_id TEXT PRIMARY KEY,
                        provider TEXT NOT NULL,
                        mode TEXT NOT NULL,
                        started_at TIMESTAMPTZ NOT NULL,
                        session_scope TEXT NOT NULL,
                        topic_count INTEGER NOT NULL,
                        symbols_json TEXT NOT NULL,
                        codes_json TEXT,
                        option_root TEXT,
                        underlying_future_symbol TEXT,
                        expiry_count INTEGER,
                        atm_window INTEGER,
                        call_put TEXT,
                        reference_price DOUBLE PRECISION,
                        status TEXT NOT NULL
                    )
                    """
                )
                cur.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb')"
                )
                if cur.fetchone()[0]:
                    cur.execute("SELECT create_hypertable('bars_1m', 'ts', if_not_exists => TRUE)")
                    cur.execute("SELECT create_hypertable('bars_1d', 'ts', if_not_exists => TRUE)")
                    cur.execute("SELECT create_hypertable('raw_ticks', 'ts', if_not_exists => TRUE)")
                    cur.execute("SELECT create_hypertable('minute_force_features_1m', 'ts', if_not_exists => TRUE)")
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
        cur.execute("ALTER TABLE bars_1m ADD COLUMN IF NOT EXISTS up_ticks DOUBLE PRECISION")
        cur.execute("ALTER TABLE bars_1m ADD COLUMN IF NOT EXISTS down_ticks DOUBLE PRECISION")
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
        cur.execute("ALTER TABLE bars_1d ADD COLUMN IF NOT EXISTS up_ticks DOUBLE PRECISION")
        cur.execute("ALTER TABLE bars_1d ADD COLUMN IF NOT EXISTS down_ticks DOUBLE PRECISION")
        cur.execute("ALTER TABLE bars_1d ADD COLUMN IF NOT EXISTS build_source TEXT")
        cur.execute("ALTER TABLE raw_ticks ADD COLUMN IF NOT EXISTS trading_day DATE")
        cur.execute("ALTER TABLE raw_ticks ADD COLUMN IF NOT EXISTS instrument_key TEXT")
        cur.execute("ALTER TABLE raw_ticks ADD COLUMN IF NOT EXISTS contract_month TEXT")
        cur.execute("ALTER TABLE raw_ticks ADD COLUMN IF NOT EXISTS strike_price DOUBLE PRECISION")
        cur.execute("ALTER TABLE raw_ticks ADD COLUMN IF NOT EXISTS call_put TEXT")
        cur.execute("ALTER TABLE raw_ticks ADD COLUMN IF NOT EXISTS session TEXT")
        cur.execute("ALTER TABLE raw_ticks ADD COLUMN IF NOT EXISTS tick_direction TEXT")
        cur.execute("ALTER TABLE raw_ticks ADD COLUMN IF NOT EXISTS total_volume DOUBLE PRECISION")
        cur.execute("ALTER TABLE raw_ticks ADD COLUMN IF NOT EXISTS bid_side_total_vol DOUBLE PRECISION")
        cur.execute("ALTER TABLE raw_ticks ADD COLUMN IF NOT EXISTS ask_side_total_vol DOUBLE PRECISION")
        cur.execute("ALTER TABLE raw_ticks ADD COLUMN IF NOT EXISTS payload_json TEXT")
        cur.execute("ALTER TABLE minute_force_features_1m ADD COLUMN IF NOT EXISTS strike_price DOUBLE PRECISION")
        cur.execute("ALTER TABLE minute_force_features_1m ADD COLUMN IF NOT EXISTS call_put TEXT")
        cur.execute("ALTER TABLE minute_force_features_1m ADD COLUMN IF NOT EXISTS run_id TEXT")
        cur.execute("ALTER TABLE live_run_metadata ADD COLUMN IF NOT EXISTS codes_json TEXT")
        cur.execute("ALTER TABLE live_run_metadata ADD COLUMN IF NOT EXISTS option_root TEXT")
        cur.execute("ALTER TABLE live_run_metadata ADD COLUMN IF NOT EXISTS underlying_future_symbol TEXT")
        cur.execute("ALTER TABLE live_run_metadata ADD COLUMN IF NOT EXISTS expiry_count INTEGER")
        cur.execute("ALTER TABLE live_run_metadata ADD COLUMN IF NOT EXISTS atm_window INTEGER")
        cur.execute("ALTER TABLE live_run_metadata ADD COLUMN IF NOT EXISTS call_put TEXT")
        cur.execute("ALTER TABLE live_run_metadata ADD COLUMN IF NOT EXISTS reference_price DOUBLE PRECISION")
        cur.execute("ALTER TABLE minute_force_features_1m ALTER COLUMN run_id SET DEFAULT ''")
        cur.execute("UPDATE minute_force_features_1m SET run_id = '' WHERE run_id IS NULL")
        cur.execute("ALTER TABLE minute_force_features_1m ALTER COLUMN run_id SET NOT NULL")

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
        cur.execute("UPDATE bars_1m SET instrument_key = symbol WHERE instrument_key IS NULL")
        cur.execute("UPDATE bars_1d SET instrument_key = symbol WHERE instrument_key IS NULL")
        cur.execute("UPDATE raw_ticks SET instrument_key = symbol WHERE instrument_key IS NULL")
        cur.execute("UPDATE raw_ticks SET contract_month = '' WHERE contract_month IS NULL")
        cur.execute("UPDATE raw_ticks SET session = 'unknown' WHERE session IS NULL")
        cur.execute("UPDATE raw_ticks SET trading_day = ts::date WHERE trading_day IS NULL")
        cur.execute("UPDATE bars_1m SET build_source = 'historical' WHERE build_source IS NULL")
        cur.execute("UPDATE bars_1d SET build_source = 'historical' WHERE build_source IS NULL")
        cur.execute("ALTER TABLE bars_1m ALTER COLUMN instrument_key SET NOT NULL")
        cur.execute("ALTER TABLE bars_1d ALTER COLUMN instrument_key SET NOT NULL")
        cur.execute("ALTER TABLE raw_ticks ALTER COLUMN instrument_key SET NOT NULL")
        cur.execute("ALTER TABLE raw_ticks ALTER COLUMN contract_month SET NOT NULL")
        cur.execute("ALTER TABLE raw_ticks ALTER COLUMN session SET NOT NULL")
        cur.execute("ALTER TABLE raw_ticks ALTER COLUMN trading_day SET NOT NULL")
        cur.execute("ALTER TABLE bars_1m ALTER COLUMN build_source SET NOT NULL")
        cur.execute("ALTER TABLE bars_1d ALTER COLUMN build_source SET NOT NULL")
        _ensure_primary_key(cur, "bars_1m", ("ts", "instrument_key", "contract_month", "session"))
        _ensure_primary_key(cur, "bars_1d", ("ts", "instrument_key", "contract_month", "session"))
        _ensure_primary_key(cur, "raw_ticks", ("ts", "instrument_key", "price", "size", "source"))
        _ensure_primary_key(cur, "minute_force_features_1m", ("ts", "instrument_key", "contract_month", "run_id"))

    @staticmethod
    def _bar_to_row(bar: Bar) -> dict:
        row = asdict(bar)
        row["ts"] = _utc(bar.ts)
        row["trading_day"] = bar.trading_day
        row["instrument_key"] = bar.instrument_key or bar.symbol
        return row

    @staticmethod
    def _tick_to_row(tick: CanonicalTick) -> dict:
        return {
            "ts": _utc(tick.ts),
            "trading_day": tick.trading_day,
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
    def _row_to_bar(row: tuple) -> Bar:
        return Bar(
            ts=_as_naive_local(row[0]),
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
            up_ticks=float(row[11]) if row[11] is not None else None,
            down_ticks=float(row[12]) if row[12] is not None else None,
            source=row[13],
            instrument_key=row[14],
            strike_price=float(row[15]) if row[15] is not None else None,
            call_put=row[16],
            build_source=row[17],
        )

    @staticmethod
    def _row_to_tick(row: tuple) -> CanonicalTick:
        return CanonicalTick(
            ts=_as_naive_local(row[0]),
            trading_day=row[1],
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
    def _feature_to_row(feature: MinuteForceFeatures) -> dict:
        return {
            "ts": _utc(datetime.fromisoformat(feature.ts)),
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
    def _row_to_feature(row: tuple) -> MinuteForceFeatures:
        return MinuteForceFeatures(
            ts=_as_naive_local(row[0]).isoformat(),
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
            started_at=_as_naive_local(row[3]),
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


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=LOCAL_TIMEZONE).astimezone(timezone.utc)
    return value.astimezone(timezone.utc)


def _as_naive_local(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(LOCAL_TIMEZONE).replace(tzinfo=None)


def _table_name(timeframe: str) -> str:
    mapping = {
        "1m": "bars_1m",
        "1d": "bars_1d",
    }
    if timeframe not in mapping:
        raise ValueError(f"Unsupported timeframe for storage: {timeframe}")
    return mapping[timeframe]


def _ensure_primary_key(cur, table: str, expected_columns: tuple[str, ...]) -> None:
    cur.execute(
        """
        SELECT con.conname,
               array_agg(att.attname ORDER BY ord.ordinality)
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN unnest(con.conkey) WITH ORDINALITY AS ord(attnum, ordinality) ON TRUE
        JOIN pg_attribute att ON att.attrelid = rel.oid AND att.attnum = ord.attnum
        WHERE rel.relname = %s AND con.contype = 'p'
        GROUP BY con.conname
        """,
        (table,),
    )
    row = cur.fetchone()
    if row and tuple(row[1]) == expected_columns:
        return
    if row:
        cur.execute(f"ALTER TABLE {table} DROP CONSTRAINT {row[0]}")
    cur.execute(f"ALTER TABLE {table} ADD PRIMARY KEY ({', '.join(expected_columns)})")
