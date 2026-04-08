# qt-platform

Research-first quantitative trading platform for Taiwan index futures.

## Scope

- Historical data ingestion from FinMind
- Session-aware storage and gap scanning
- Event-driven backtesting on 1-minute bars
- CLI-driven workflow and HTML report generation

## Quick Start

1. Copy `config/config.yaml.example` to `config/config.yaml`
2. Copy `.env.example` to `.env` and set `FINMIND_TOKEN`
3. Start TimescaleDB
4. Run sync or backtest commands against either `sqlite:///local.db` or `postgresql://...`

```bash
docker compose up -d
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml scan-gaps --symbol TX --start 2024-01-01T08:45:00 --end 2024-01-02T13:45:00
PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml backfill --database-url postgresql://postgres:postgres@localhost:5432/trading --symbol TX --start-date 2024-01-01 --end-date 2024-01-31 --timeframe 1m
```

## Notes

- V1 canonical storage is `bars_1m` only. Raw tick data is not stored.
- `1m` and `1d` are stored in separate tables (`bars_1m`, `bars_1d`). They are never mixed.
- SQLite remains available for local tests and simple experiments.
- PostgreSQL/TimescaleDB storage is supported through the repository layer.
- FinMind integration uses `urllib` to avoid forcing a runtime HTTP client.
- FinMind minute ingestion is implemented by aggregating `TaiwanFuturesTick` into 1-minute bars.
- `TaiwanFuturesTick` requires a Sponsor-capable FinMind account. With a free-level token, `1m` backfill will fail upstream even though the pipeline is implemented.
- Important data structures are documented in `docs/SCHEMA.md`.
