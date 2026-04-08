CREATE EXTENSION IF NOT EXISTS timescaledb;

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
);

SELECT create_hypertable('bars_1m', 'ts', if_not_exists => TRUE);

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
