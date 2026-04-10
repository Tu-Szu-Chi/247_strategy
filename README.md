# qt-platform

Research-first quantitative trading platform for Taiwan index futures.

## Scope

- Historical data ingestion from FinMind
- Session-aware storage and gap scanning
- Event-driven backtesting on 1-minute bars
- CLI-driven workflow and HTML report generation

## Quick Start

1. Copy `config/config.yaml.example` to `config/config.yaml`
2. Copy `config/symbols.csv.example` to `config/symbols.csv`
3. Copy `.env.example` to `.env` and set `FINMIND_TOKEN`
4. Start TimescaleDB
5. Run sync or backtest commands against either `sqlite:///local.db` or `postgresql://...`

```bash
docker compose up -d
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml scan-gaps --symbol MTX --start 2024-01-01T08:45:00 --end 2024-01-02T13:45:00 --session-scope day_and_night
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml plan-sync --database-url postgresql://postgres:postgres@localhost:5432/trading --start-date 2024-01-01 --end-date 2024-01-31
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml sync-registry --database-url postgresql://postgres:postgres@localhost:5432/trading --start-date 2024-01-01 --end-date 2024-01-31
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml backfill --database-url postgresql://postgres:postgres@localhost:5432/trading --symbol MTX --start-date 2024-01-01 --end-date 2024-01-31 --timeframe 1m
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml doctor --database-url postgresql://postgres:postgres@localhost:5432/trading --symbol MTX --timeframe 1m
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml resolve-contract --symbol MTX --date 2024-01-18
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml backtest --database-url postgresql://postgres:postgres@localhost:5432/trading --symbol MTX_MAIN --start 2024-01-03T08:45:00 --end 2024-01-03T13:44:00 --timeframe 1m
```

## Notes

- V1 canonical storage is `bars_1m` only. Raw tick data is not stored.
- `1m` and `1d` are stored in separate tables (`bars_1m`, `bars_1d`). They are never mixed.
- SQLite remains available for local tests and simple experiments.
- PostgreSQL/TimescaleDB storage is supported through the repository layer.
- FinMind integration uses `urllib` to avoid forcing a runtime HTTP client.
- FinMind minute ingestion is implemented by aggregating `TaiwanFuturesTick` into 1-minute bars.
- The working primary symbol for current examples and smoke tests is `MTX`.
- `MTX_MAIN` is supported as a continuous monthly-contract view for read-side workflows such as backtest and doctor.
- `plan-sync` reads `config/symbols.csv` and estimates request cost before running any actual sync.
- `sync-registry` executes historical sync from `config/symbols.csv`. In the current phase it runs `bootstrap` and `catch_up`, while `repair` is intentionally skipped unless `--allow-repair` is passed.
- `1d` planning assumes FinMind bulk-daily requests can fetch all futures symbols for one date in one request.
- `1m` planning assumes one request per `symbol + date`, and currently checks `trading_day` presence only rather than minute-level completeness.
- `sync-registry` currently supports `TAIFEX futures 1d/1m`, `TWSE stocks 1d`, and `TAIFEX TXO 1d` through FinMind.
- `config/symbols.csv` now supports `instrument_type`, so futures / options / stocks can coexist in the registry without forcing the current provider to sync unsupported products.
- For Taiwan index options, `TXO` is the only FinMind `TaiwanOptionDaily` id currently kept in the active registry. Other TAIFEX option product codes should be re-added only after provider behavior is verified.
- `TaiwanOptionDaily` should use `v4` single-day windows. The older `v3 + date` path was observed to hang on real requests.
- Option daily storage must key on `instrument_key` instead of bare `symbol`, or one trading day of `TXO` chain data will overwrite itself.
- `TaiwanFuturesTick` requires a Sponsor-capable FinMind account. With a free-level token, `1m` backfill will fail upstream even though the pipeline is implemented.
- Important data structures are documented in `docs/SCHEMA.md`.
- Data-source boundaries and pipeline design are documented in `docs/DATA_PIPELINE.md`.
- Environment bootstrap / backup / restore / resync workflow is documented in `docs/OPERATIONS.md`.
