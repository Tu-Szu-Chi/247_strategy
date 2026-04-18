-- Check historical shioaji_live option ticks whose symbol was flattened to TX
-- even though instrument_key indicates a weekly/monthly TX option root such as
-- TX4 / TXU / TXV / TXX / TXY / TXZ / TXO.

WITH candidate_rows AS (
    SELECT
        ts,
        trading_day,
        session,
        symbol,
        instrument_key,
        contract_month,
        strike_price,
        call_put,
        price,
        size,
        source,
        substring(instrument_key FROM '^(TXO|TX[1-5UVXYZ])') AS expected_symbol
    FROM raw_ticks
    WHERE source = 'shioaji_live'
      AND symbol = 'TX'
      AND instrument_key ~ '^(TXO|TX[1-5UVXYZ])'
)
SELECT
    expected_symbol,
    COUNT(*) AS tick_count,
    MIN(ts) AS first_ts,
    MAX(ts) AS last_ts,
    COUNT(DISTINCT trading_day) AS trading_days
FROM candidate_rows
GROUP BY expected_symbol
ORDER BY expected_symbol;


WITH candidate_rows AS (
    SELECT
        ts,
        trading_day,
        session,
        symbol,
        instrument_key,
        contract_month,
        strike_price,
        call_put,
        price,
        size,
        source,
        substring(instrument_key FROM '^(TXO|TX[1-5UVXYZ])') AS expected_symbol
    FROM raw_ticks
    WHERE source = 'shioaji_live'
      AND symbol = 'TX'
      AND instrument_key ~ '^(TXO|TX[1-5UVXYZ])'
)
SELECT
    ts,
    trading_day,
    session,
    symbol AS current_symbol,
    expected_symbol,
    instrument_key,
    contract_month,
    strike_price,
    call_put,
    price,
    size
FROM candidate_rows
ORDER BY ts DESC
LIMIT 200;
