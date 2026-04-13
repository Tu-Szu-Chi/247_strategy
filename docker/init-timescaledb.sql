CREATE EXTENSION IF NOT EXISTS timescaledb;

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
);

SELECT create_hypertable('bars_1m', 'ts', if_not_exists => TRUE);

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
);

SELECT create_hypertable('bars_1d', 'ts', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS sync_state (
    source TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    session_scope TEXT NOT NULL,
    cursor_ts TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source, symbol, timeframe, session_scope)
);

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
);

SELECT create_hypertable('raw_ticks', 'ts', if_not_exists => TRUE);

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
);

SELECT create_hypertable('minute_force_features_1m', 'ts', if_not_exists => TRUE);

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
);
