# V1 Implementation Notes

## Implemented

- Python project scaffold under `src/qt_platform`
- FinMind futures provider with throttling and retry
- FinMind futures tick aggregation into 1-minute bars
- Repository abstraction with SQLite and PostgreSQL/TimescaleDB backends
- Timeframe-aware storage separation: `bars_1m` and `bars_1d`
- Gap scanning and backfill maintenance service
- Event-driven backtest engine with next-bar-open fills
- Basic SMA crossover strategy
- HTML report generation
- CLI commands: `scan-gaps`, `backfill`, `backtest`
- Docker Compose + TimescaleDB init SQL for production-oriented storage setup
- Basic tests for provider normalization, gap scan, and fill timing
- `docs/SCHEMA.md` for high-value structures and storage semantics
- Verified: PostgreSQL daily backfill/read path works; `1m` path is implemented but upstream-gated by FinMind Sponsor requirement
