# Repository Guidelines

## Project Structure & Module Organization
Core application code lives in `src/qt_platform/`. Key areas include `cli/` for command entry points, `backtest/` for simulation, `live/` for real-time ingestion, `monitor/` for replay/live research services, `storage/` for persistence, `kronos/` for probability-model integration, and `market_state/` plus `trading_calendar.py` for shared MTX/session rules. The frontend app lives in `frontend/` as `React + Vite + TypeScript`; `src/qt_platform/web/` is the FastAPI wrapper that serves API routes and built frontend assets. Tests are in `tests/` and generally mirror the module they cover, for example `tests/test_option_power_replay.py`. Runtime configuration lives in `config/`, operational notes in `docs/`, vendored third-party model code lives in `vendor/Kronos/`, and database/bootstrap assets live in `docker/` and `analysis/`.

## Important files
Read these first when changing behavior or architecture:

- `AGENTS.md`
- `README.md`
- `PLAN.md`
- `NOTE.md`
- `spec/**/*.md`
- `docs/ARCHITECTURE.md`
- `docs/OPERATIONS.md`
- `docs/SCHEMA.md`
- `docs/DATA_PIPELINE.md`

## Build, Test, and Development Commands
Use Python 3.10+.

- `python3.10 -m venv .venv && source .venv/bin/activate` creates the local environment on Unix-like systems.
- `py -3.10 -m venv .venv` and `.\.venv\Scripts\Activate.ps1` do the same on Windows.
- `pip install -e .[web,live,reports,kronos]` installs the package plus optional web/live/report/Kronos tooling. `pytest` is already a required dependency in the base install.
- `docker compose up -d` starts TimescaleDB from [`docker-compose.yml`](/C:/Users/tost8/Documents/247_strategy/docker-compose.yml).
- `PYTHONPATH=src python -m qt_platform.cli.main --config config/config.yaml data doctor --symbol MTX --timeframe 1m` validates config, DB access, and basic command wiring.
- `PYTHONPATH=src python -m pytest` runs the full test suite.
- `PYTHONPATH=src python -m qt_platform.cli.main backtest run --help` is the fastest way to inspect current backtest CLI behavior before changing it.
- `PYTHONPATH=src python -m qt_platform.cli.main monitor live --help`
- `PYTHONPATH=src python -m qt_platform.cli.main monitor replay --help`
- `PYTHONPATH=src python -m qt_platform.cli.main data --help`
- `PYTHONPATH=src python -m qt_platform.cli.main kronos probability --help`

## Coding Style & Naming Conventions
Follow the existing Python style: 4-space indentation, type hints on public functions, and small focused modules. Use `snake_case` for files, functions, and variables; `PascalCase` for classes; and `UPPER_SNAKE_CASE` for constants like `LIVE_SUBSCRIBE_LEAD_SECONDS`. Keep CLI flags descriptive and hyphenated, matching current patterns such as `--database-url`, `--session-scope`, and `--snapshot-interval-seconds`. No formatter or linter is configured in `pyproject.toml`, so keep changes consistent with surrounding code and imports.

When touching naming or boundaries:

- `qt_platform.market_state.mtx` is the MTX-specific market-state adapter.
- `qt_platform.trading_calendar` is the shared session/trading-day boundary module.
- `regime` is still preserved in external snapshot payloads for compatibility, but new internal code should prefer `market_state` terminology.

## Testing Guidelines
Tests run with `pytest`, but many suites use `unittest.TestCase`; both patterns are accepted. Name files `test_<module>.py` and keep test names behavior-focused, such as `test_signal_fills_on_next_open`. Add or update tests whenever changing sync planning, session logic, storage adapters, replay/live materialization, or live-recording behavior. Prefer targeted runs during development, for example `PYTHONPATH=src python -m pytest tests/test_session.py -q` or `PYTHONPATH=src python -m unittest tests.test_session`.

## Commit & Pull Request Guidelines
Recent history uses short imperative commit messages like `fix live record bug` and `add UI`. Keep commits small, specific, and lowercase unless a proper noun requires otherwise. Pull requests should explain the user-visible behavior change, list affected commands or config keys, and include screenshots when touching `frontend/` or served research UI behavior.

## Configuration & Safety Notes
Do not commit live credentials or edited secrets files. Treat `config/config.yaml.example` and `config/symbols.csv.example` as templates, and document any new environment variables in `README.md` when adding them.

Do not commit generated or machine-local artifacts such as:

- `.env`
- `logs/`
- `reports/`
- `*.db`
- `*.egg-info/`
- `.DS_Store`
- vendored model outputs such as `vendor/Kronos/webui/prediction_results/`

## Note
Once you finish the implementation, Claude code will review it.
