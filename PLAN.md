# V1 Implementation Notes

## Implemented

- Python project scaffold under `src/qt_platform`
- FinMind futures provider with throttling and retry
- FinMind futures tick aggregation into 1-minute bars
- Repository abstraction with SQLite and PostgreSQL/TimescaleDB backends
- Timeframe-aware storage separation: `bars_1m` and `bars_1d`
- Session-aware gap scan for MTX intraday data
- Trading-day aware night-session semantics for after-midnight bars
- Gap scanning and backfill maintenance service
- Event-driven backtest engine with next-bar-open fills
- Basic SMA crossover strategy
- HTML report generation
- CLI commands: `scan-gaps`, `backfill`, `backtest`, `plan-sync`, `sync-registry`, `doctor`, `resolve-contract`
- Docker Compose + TimescaleDB init SQL for production-oriented storage setup
- Basic tests for provider normalization, gap scan, and fill timing
- `docs/SCHEMA.md` for source-agnostic schema semantics
- `docs/DATA_PIPELINE.md` for provider/pipeline boundaries
- Registry-driven sync planning from `config/symbols.csv`
- Historical sync execution for registry bootstrap/catch-up
- Verified: PostgreSQL daily backfill/read path works; `1m` path is implemented but upstream-gated by FinMind Sponsor requirement

## Current Direction

The current direction is no longer "build everything at once". The near-term implementation order is:

1. stabilize historical ingestion and backtest workflow
2. define strategy-facing feature interfaces
3. add live monitoring pipeline
4. add execution / risk / UI on top of stable data contracts

This order is intentional. Live subscription and trading should not be the first integration point while historical data contracts are still moving.

## User Story Implementation Plan

### Phase 1: Historical Foundation

Target:
- make `bars_1m` / `bars_1d` reliable
- make broker CSV import and FinMind sync coexist cleanly
- make backtest and research read from one canonical storage layer

Scope:
- keep `bars_1m` as the main intraday research table
- keep `bars_1d` for bootstrap and option OI studies
- support:
  - FinMind futures `1m`
  - FinMind stocks `1d`
  - FinMind `TXO` `1d`
  - broker-exported `1m CSV`
- keep `up_ticks/down_ticks` as optional minute-level force inputs

Planned next historical extension:
- `TXO 1m historical` should use `FinMind TaiwanOptionTick -> bars_1m`
- universe is intentionally constrained as Version A:
  - option root: `TXO`
  - recent `2` expiries only
  - `ATM ±20`
  - `call + put`
- this is meant to align historical option minute data with the current live resolver universe
- full-chain `TXO` historical backfill is explicitly deferred

Deliverables:
- completed repository schema
- importer/sync commands
- strategy-facing minute feature functions
- JSON backtest report output

### Phase 2: Strategy Interface Unification

Target:
- avoid writing one strategy for backtest and another for live

Direction:
- define one strategy interface that can consume:
  - `on_bar(context)`
  - later `on_tick(context)`
- keep the input model canonical and source-agnostic
- strategy should not know whether the bar came from:
  - FinMind
  - broker CSV
  - live tick aggregation

Recommended implementation:
- add a `MarketContext` or `StrategyContext`
- include:
  - current `Bar`
  - optional minute force features
  - symbol metadata
  - position state
- backtest engine and live engine should both call the same strategy methods

### Phase 3: Live Monitoring Runtime

Target:
- satisfy the SPEC startup/runtime story without prematurely coupling to one broker

Recommended design:
- add `BaseLiveProvider`
  - `connect()`
  - `subscribe(symbols)`
  - `close()`
  - callback/event queue output
- implement live runtime service separately from historical providers
- runtime loop:
  - detect whether current time is in tradable session
  - if yes:
    - connect websocket
    - subscribe configured symbols
    - persist incoming live events
    - aggregate to `bars_1m`
    - evaluate strategy
    - persist emitted signals
  - if no:
    - compute next session open
    - sleep/schedule until open

Important:
- this should be a dedicated service/module, not hidden inside the current CLI backfill path

### Phase 4: Signal Persistence and Replay

Target:
- satisfy "signal needs to be stored to DB for review"

Need new tables:
- `signals`
- later `orders`, `fills`, `positions`

Minimum `signals` schema:
- `ts`
- `symbol`
- `strategy_id`
- `signal_type`
- `side`
- `reason`
- `payload_json`
- `source_mode` (`backtest` / `live`)

This will let UI and post-trade review use one storage model.

### Phase 5: UI Contract

Target:
- keep UI simple and decoupled from engine internals

Recommended contract:
- UI subscribes only to stable topics/events:
  - `signals`
  - `bars_1m`
- backtest output should be written as JSON report files
- UI renders report JSON instead of reading Python objects directly

Recommended outputs:
- `report.json`
- `trades.json`
- `equity_curve.json`

This is preferable to binding UI directly to QuantStats HTML as the primary artifact.

### Phase 6: Execution Layer

Target:
- keep execution replaceable and isolated from strategy logic

Recommended interfaces:
- `BaseExecutor`
  - `submit_order(intent)`
  - `cancel_order(order_id)`
  - `get_positions()`
- implementations:
  - `MockExecutor`
  - later `ShioajiExecutor` or `KgiExecutor`

Risk checks should sit between strategy and executor, not inside the strategy.

## Recommended Next Steps

1. add JSON backtest report persistence as the primary report artifact
2. define `StrategyContext` and unify strategy inputs for research/live
3. add `signals` table and persistence flow
4. only then start live runtime service and websocket subscription orchestration

## Live Recorder Slice

This slice is intentionally pulled earlier than the rest of live runtime.

Goal:
- start storing live option/futures ticks as soon as possible
- preserve broker-only fields that historical providers cannot reconstruct later

Current implementation target:
- `CanonicalTick`
- `raw_ticks` table
- `BaseLiveProvider`
- `LiveRecorderService`
- `record-live-stub` CLI for contract/path validation

Not included yet:
- real broker websocket integration
- auto session scheduler
- signal emission
- execution

## What Not To Do Yet

- do not start auto-order execution before `signals` and `MockExecutor` are stable
- do not bind strategy code directly to broker SDK payloads
- do not let UI read database/vendor-specific raw payloads as its primary contract
- do not mix live orchestration logic into `sync-registry` or historical maintenance paths
