# Repository Guidelines

## Project Structure & Module Organization
Core application code lives in `src/qt_platform/`. Key areas include `cli/` for command entry points, `backtest/` for simulation, `live/` for real-time ingestion, `storage/` for persistence, and `web/static/` for the option-power UI. Tests are in `tests/` and generally mirror the module they cover, for example `tests/test_sync_planner.py`. Runtime configuration lives in `config/`, operational notes in `docs/`, and database/bootstrap assets in `docker/` and `analysis/`.

## Important files
./spec/**.md, AGENTS.md, README.md, NOTE.md, PLAN.md 

## Build, Test, and Development Commands
Use Python 3.10+.

- `python3.10 -m venv .venv && source .venv/bin/activate` creates the local environment.
- `pip install -e .[dev,web,live,reports]` installs the package plus optional tooling used in this repo.
- `docker compose up -d` starts TimescaleDB from [`docker-compose.yml`](/Users/quentin-tu/Documents/247_strategy/docker-compose.yml).
- `PYTHONPATH=src python3.10 -m qt_platform.cli.main --config config/config.yaml doctor` validates config, DB connectivity, and upstream access.
- `PYTHONPATH=src pytest` runs the full test suite.
- `PYTHONPATH=src python3.10 -m qt_platform.cli.main backtest --help` is the fastest way to inspect CLI workflows before changing them.

## Coding Style & Naming Conventions
Follow the existing Python style: 4-space indentation, type hints on public functions, and small focused modules. Use `snake_case` for files, functions, and variables; `PascalCase` for classes; and `UPPER_SNAKE_CASE` for constants like `LIVE_SUBSCRIBE_LEAD_SECONDS`. Keep CLI flags descriptive and hyphenated, matching current patterns such as `--database-url` and `--session-scope`. No formatter or linter is configured in `pyproject.toml`, so keep changes consistent with surrounding code and imports.

## Testing Guidelines
Tests run with `pytest`, but many suites use `unittest.TestCase`; both patterns are accepted. Name files `test_<module>.py` and keep test names behavior-focused, such as `test_signal_fills_on_next_open`. Add or update tests whenever changing sync planning, session logic, storage adapters, or live-recording behavior. Prefer targeted runs during development, for example `PYTHONPATH=src pytest tests/test_session.py`.

## Commit & Pull Request Guidelines
Recent history uses short imperative commit messages like `fix live record bug` and `add UI`. Keep commits small, specific, and lowercase unless a proper noun requires otherwise. Pull requests should explain the user-visible behavior change, list affected commands or config keys, link related issues, and include screenshots when touching `src/qt_platform/web/static/`.

## Configuration & Safety Notes
Do not commit live credentials or edited secrets files. Treat `config/config.yaml.example` and `config/symbols.csv.example` as templates, and document any new environment variables in `README.md` when adding them.

## Note
Once you finish the implementation, Claude code will review it