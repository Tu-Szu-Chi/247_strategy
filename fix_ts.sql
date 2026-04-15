-- Fix timezone-shifted timestamps caused by treating Asia/Taipei local naive datetimes
-- as UTC when inserting into PostgreSQL / TimescaleDB.
--
-- Symptom:
--   local 2026-04-15 09:00 Asia/Taipei
--   was stored as 2026-04-15 09:00+00
--   and displayed in GMT+8 as 2026-04-15 17:00+08
--
-- Correct storage should be:
--   2026-04-15 01:00+00
--
-- This script shifts affected TIMESTAMPTZ columns back by 8 hours.
--
-- WARNING:
-- 1. Run this only for data written BEFORE the timezone fix in code.
-- 2. If you already have newly-written corrected rows mixed in, do not run this blindly on the whole table.
-- 3. Recommended: backup first.

BEGIN;

-- Main tables explicitly confirmed affected.
UPDATE bars_1m
SET ts = ts - INTERVAL '8 hours';

UPDATE raw_ticks
SET ts = ts - INTERVAL '8 hours';

-- Optional related tables.
-- Uncomment if you want all live/runtime-related timestamps to stay aligned.
--
-- UPDATE minute_force_features_1m
-- SET ts = ts - INTERVAL '8 hours';
--
-- UPDATE live_run_metadata
-- SET started_at = started_at - INTERVAL '8 hours';
--
-- UPDATE sync_state
-- SET cursor_ts = cursor_ts - INTERVAL '8 hours'
-- WHERE cursor_ts IS NOT NULL;
--
-- UPDATE bars_1d
-- SET ts = ts - INTERVAL '8 hours';

COMMIT;

-- Suggested verification after running:
-- SELECT ts, ts AT TIME ZONE 'Asia/Taipei' AS taipei_ts, symbol, instrument_key
-- FROM raw_ticks
-- ORDER BY ts DESC
-- LIMIT 10;
