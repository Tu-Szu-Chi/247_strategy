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

## 2026-05-01 Option Power Registry Subscription Plan

Context:
- `scripts/start-option-power.ps1` currently launches `serve-option-power`.
- `serve-option-power` subscribes only to:
  - `underlying_future_symbol`
  - resolved option contracts from `resolve_option_universe(...)`
- `runtime` already has the missing piece for registry-driven stock subscription:
  - load `config/symbols.csv`
  - keep enabled `instrument_type=stock`
  - resolve those contracts through `ShioajiLiveProvider`
  - persist ticks and aggregate `bars_1m`
- operationally, `runtime` is now deprecated, so registry stock capture must move into the `serve-option-power` process.

Target:
- make `serve-option-power` optionally subscribe live ticks for `symbols.csv` stocks in the same process that powers the option-power UI
- keep one long-running process for:
  - option-power live computation
  - underlying future live capture
  - registry stock live capture
- avoid a second parallel runtime process

### Design Decision

Recommended direction:
- do not embed the old `_runtime_universe_from_registry()` flow directly into CLI glue only
- instead, move registry stock resolution into a reusable helper that both `runtime` and `serve-option-power` can call
- keep option-power as the orchestrator, but let its runtime service own one combined subscription universe

Reason:
- current `runtime` and `RealtimeMonitorService` already duplicate pieces of:
  - `provider.connect()`
  - contract resolution
  - tick persistence
  - `bars_1m` aggregation
- copying one more registry branch into `serve-option-power` would increase divergence again
- the clean direction is "shared universe builder + shared tick persistence semantics", while keeping the option snapshot logic local to option-power

### Proposed Scope

1. CLI and script surface
- add `--registry` to `serve-option-power`
- default to `settings.sync.registry_path` when omitted
- add a switch like `--subscribe-registry-stocks` if you want explicit opt-in
- simpler default is to always load registry stocks when `registry` exists; this matches the current operational intent better
- update `scripts/start-option-power.ps1` to pass `--registry config/symbols.csv`

2. Shared registry helpers
- extract a reusable helper from `cli/main.py`:
  - current source is `_runtime_universe_from_registry(registry_path)`
- move it into a dedicated module, for example:
  - `src/qt_platform/live/universe.py`
- helper output should be more explicit than the current tuple:
  - `registry_stock_symbols`
  - maybe later `registry_future_symbols`
  - maybe later `registry_option_roots`
- for this slice, only `stock` entries need to become live subscriptions

3. Option-power runtime subscription model
- extend `RealtimeMonitorService` constructor with registry inputs, for example:
  - `registry_path: str | None`
  - or already-parsed `registry_stock_symbols: list[str]`
- inside `_run_cycle()`:
  - resolve option contracts as today
  - resolve `underlying_future_symbol` as today
  - additionally resolve each registry stock contract through `provider._resolve_contract(symbol)`
  - build one unified `all_contracts` list:
    - underlying future
    - registry stocks
    - resolved option contracts
  - de-duplicate by `code` / `target_code`
  - stream through one `stream_ticks_from_contracts(...)`

4. Persistence expectations
- no new storage table is required
- existing live tick persistence path already writes:
  - `raw_ticks`
  - aggregated `bars_1m`
  - minute force features
- this means once registry stocks are in the unified contract list, `2330` and peers will automatically land in `bars_1m`
- `LiveRunMetadata.symbols_json` and `codes_json` should include registry stocks so post-run inspection is accurate

5. Logging and observability
- current option-power logs report subscription status, but not registry composition
- add fields such as:
  - `registry_path`
  - `registry_stock_count`
  - `registry_stock_symbols`
  - `topic_count`
- when registry loading fails:
  - fail fast if the feature is considered required for production
  - otherwise emit warning and continue with option-only mode
- for your current setup, fail fast is safer; silent degradation is exactly how `2330` got stale unnoticed

### Refactor Boundary

Keep:
- option-power-specific snapshot generation
- option-power replay service
- option root resolution logic

Share or extract:
- registry parsing and filtering
- live universe assembly
- contract de-duplication

Do not do in this slice:
- merge the entire deprecated `runtime` scheduler into option-power
- add multi-threaded dual consumers on the same provider queue
- create a second independent `LiveRecorderService.record(...)` loop inside option-power

Reason:
- `ShioajiLiveProvider` exposes a single streaming queue
- two concurrent consumers in one process would race and split ticks unpredictably
- the correct model is one stream consumer, one persistence path, one runtime owner

### Implementation Sketch

Suggested sequence:

1. Add a small shared helper module for registry live symbols
- move registry stock extraction out of `cli/main.py`
- keep behavior identical to current `runtime`

2. Extend `serve-option-power` parser
- add `--registry`
- wire it into `_serve_option_power(...)`

3. Extend `RealtimeMonitorService`
- accept `registry_stock_symbols`
- resolve and append stock contracts inside `_run_cycle()`
- include them in metadata and subscription log payloads

4. Update `scripts/start-option-power.ps1`
- pass the registry path explicitly
- print the registry path in startup output

5. Update docs
- `README.md`
- maybe `docs/OPERATIONS.md`
- clarify that `serve-option-power` is now the canonical live recorder for:
  - option-power universe
  - registry stocks

### Testing Plan

Unit tests:
- registry helper returns only enabled `instrument_type=stock`
- `serve-option-power` parser accepts `--registry`
- runtime metadata includes registry symbols when configured
- contract de-duplication still works when stock, underlying, and option lists overlap

Integration tests:
- stub provider emits ticks for:
  - one underlying future
  - one option contract
  - one registry stock such as `2330`
- verify one run persists all three into:
  - `raw_ticks`
  - `bars_1m`
- verify `LiveRunMetadata.symbols_json` contains `2330`

Operational verification:
- launch `start-option-power.ps1`
- confirm log contains `registry_stock_count > 0`
- query PostgreSQL:
  - latest `bars_1m.ts` for `2330`
  - latest `bars_1m.ts` for `MXFR1`
  - recent `live_run_metadata.symbols_json`

### Risks

- More subscribed stock symbols means higher quote traffic and Shioaji usage consumption.
- The option-power runtime may hit usage thresholds earlier than before.
- If `symbols.csv` grows large, startup contract resolution latency will increase.
- UI runtime and data-recorder runtime are now even more tightly coupled, so process failure impacts both monitoring and stock ingestion.

### Mitigations

- start with `stock` entries only, not all registry instrument types
- log usage status and subscribed topic count prominently
- consider a future cap such as `enabled` plus `live_subscribe=true` if registry size grows
- keep `history-sync` as the repair/backfill path for missed intraday sessions

### Recommended Decision

Recommended implementation:
- make `serve-option-power` the single canonical live process
- add registry-stock subscription directly into `RealtimeMonitorService`
- reuse the existing registry parsing logic via a shared helper
- fail fast when the configured registry file is missing or invalid

This gives you one process with clear operational semantics:
- option-power UI works
- underlying future and options keep updating
- `symbols.csv` stocks such as `2330` keep writing into `bars_1m`
