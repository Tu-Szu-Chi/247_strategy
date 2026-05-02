# Polars Indicator Backend Plan

Note:

- `bias_signal`, `signal_state`, and the old `option-power-signal` strategy were removed from the active codebase on 2026-05-01.
- Historical notes below may still mention them as implementation history; they are no longer current behavior.

## Goal

Move decision-grade option-power and MTX regime indicator calculations out of frontend/replay Python loops and into backend batch computation. The target is a canonical backend indicator frame keyed by `time`, with frontend code responsible for rendering, selection, and resampling only.

## Scope

- First phase: historical replay and backtest-oriented batch computation.
- Live path should remain behavior-compatible unless a later milestone explicitly changes live ingestion.
- No database schema migration and no Parquet/cache persistence in this phase.

## Current State

Backend indicators before this phase:

- Option pressure from `MonitorAggregator`: `pressure_index`, `raw_pressure`, `pressure_index_weighted`, `raw_pressure_weighted`.
- Replay series mapping in `src/qt_platform/option_power/replay.py`: pressure fields, `regime_state`, `structure_state`, regime numeric fields, string-state encodings, and `iv_skew`.
- MTX regime fields from `src/qt_platform/market_state/mtx.py`: `trend_score`, `chop_score`, `reversal_risk`, `adx_14`, `di_bias_14`, CVD fields, compression/expansion fields, and related context.

Frontend-derived indicators in `frontend/src/pages/OptionPowerResearchWorkspace.tsx`:

- Trend quality: `trend_quality_score`.
- Trend bias: `trend_bias_state`.
- Flow impulse: `flow_impulse_score`.
- Flow state: `flow_state`.
- Range state: `range_state`.
- Bias: `bias_signal`.
- Signal: `signal_state`.

## Target Architecture

- Build a backend in-memory indicator frame keyed by `time`.
- Keep pressure math in a backend helper shared by batch and `MonitorAggregator`.
- Use Polars as the batch frame engine when installed.
- Keep pure Python formula helpers for parity, unit testing, and compatibility while environments finish installing the new dependency.
- Expose canonical indicator series names from one backend module so replay metadata, API responses, and frontend requests stay aligned.
- Separate full-resolution indicator computation from viewport queries:
  - Level 1 cache: full-resolution indicator series for each replay session.
  - Level 2 cache: viewport-ready slices keyed by range, interval, requested names, and target point count.
- Frontend replay requests should be visible-range first, with buffer and target point count, instead of treating broad replay windows as chart lifecycle boundaries.
- Indicator zoom/pan should slice and downsample cached series, not recompute indicators.
- Replay compute remains asynchronous; partial responses must expose coverage so the frontend can distinguish "not computed yet" from "no data".

## Indicator Inventory

- Pressure: `pressure_index`, `raw_pressure`, `pressure_index_weighted`, `raw_pressure_weighted`.
- Regime: `regime_state`, `trend_score`, `chop_score`, `reversal_risk`.
- Structure: `structure_state`.
- Trend quality: `trend_quality_score`, `trend_bias_state`, `adx_14`, `di_bias_14`, `choppiness_14`.
- Flow: `flow_impulse_score`, `flow_state`, `session_cvd`, `cvd_5b_delta`, `cvd_15b_delta`, `cvd_5b_slope`, `cvd_price_alignment`, `price_cvd_divergence_15b`.
- Range: `range_ratio_5b_30b`, `compression_score`, `expansion_score`, `compression_expansion_state`, `range_state`.
- Bias: `bias_signal`.
- Signal: `signal_state`.
- Volatility surface context: `iv_skew`.

## Milestones

- [x] Add docs plan/work-log file.
- [x] Add Polars dependency and backend batch module scaffold.
- [x] Port frontend-derived formulas to backend as pure Python/Polars-compatible functions.
- [x] Add Polars pressure batch computation matching `MonitorAggregator`.
- [x] Add canonical backend series names for derived indicators.
- [x] Wire replay series output to consume backend-computed series/extras.
- [x] Remove frontend decision-grade derived calculations from the rendering path, leaving direct backend series consumption and resampling.
- [x] Add parity tests for pressure math and frontend-derived signal helper cases.
- [x] Add benchmark smoke test over a larger replay window.
- [x] Wire backtest strategy/runtime consumers to backend-computed series/extras.
- [x] Add CLI or replay-service helper for producing backtest-ready option-power indicator series from stored data.
- [x] Add an option-power-aware strategy definition that consumes `signal_state` / `bias_signal` from `StrategyContext.extras`.
- [x] Add compact backtest fill/report annotations with the option-power indicator values used by each signal.
- [x] Add a compact annotated fill CSV export for UI/backtest timeline comparison.
- [x] Remove stale frontend decision-grade formula helpers after backend parity coverage replaced them.
- [x] Add replay Level 1 full-resolution indicator cache.
- [x] Add range/coverage metadata to replay series and bundle responses.
- [x] Add viewport target point count / downsampling support for replay series queries.
- [x] Refactor frontend replay data flow around visible-range buffered slices instead of window lifecycle resets.
- [x] Expand replay async events from coarse progress to range/series readiness.
- [x] Add browser-level replay UX smoke test coverage.

## Work Log

### 2026-04-29

Completed change:

- Added `src/qt_platform/option_power/indicator_backend.py`.
- Added `polars>=1.0,<2.0` to `pyproject.toml`.
- Moved pressure metric math into a backend helper and made `MonitorAggregator` delegate to it.
- Added backend canonical series names, including `trend_quality_score`, `trend_bias_state`, `flow_impulse_score`, `flow_state`, `range_state`, `bias_signal`, and `signal_state`.
- Made replay `_build_indicator_series` delegate to backend batch series construction.
- Updated `OptionPowerResearchWorkspace.tsx` to request and render backend-derived series directly.
- Added `tests/test_option_power_indicator_backend.py`.

Files touched:

- `pyproject.toml`
- `src/qt_platform/option_power/indicator_backend.py`
- `src/qt_platform/option_power/aggregator.py`
- `src/qt_platform/option_power/replay.py`
- `frontend/src/pages/OptionPowerResearchWorkspace.tsx`
- `tests/test_option_power_indicator_backend.py`
- `docs/POLARS_INDICATOR_BACKEND_PLAN.md`

Tests run:

- `PYTHONPATH=src .venv/bin/python -m unittest tests.test_option_power_indicator_backend tests.test_option_power_aggregator tests.test_option_power_replay` passed, exercising the compatibility path.
- `npm test -- src/pages/OptionPowerResearchWorkspace.test.ts` passed.
- `npm run build` passed.
- `PYTHONPATH=src .venv/bin/python - <<'PY' ...` import check passed and reported `polars_loaded False`, `series_count 36`.
- `PYTHONPATH=src .venv/bin/python -m compileall -q src/qt_platform/option_power tests/test_option_power_indicator_backend.py` passed.

Known mismatch/blocker:

- `.venv` initially lacked `pytest` and `polars`, so the first `pytest` command could not run.
- Dependency installation was attempted with approved network access, but the `polars-runtime-32` wheel download stalled for several minutes and was stopped. `indicator_backend.pl is not None` currently prints `False` in this `.venv`.

Next concrete step:

### 2026-04-30 Replay Cold-Path Investigation

Observed production behavior on the replay API:

- Hot `bundle-by-bars` request on an already-materialized range returned in about `157ms`.
- Cold `bundle-by-bars` request on a new range beyond `indicator_cache_until` took about `26.1s`.

Important findings:

- The slow path is not the Polars formula stage.
- The expensive part is replay-time materialization:
  - fetch raw ticks
  - advance Python `MonitorAggregator`
  - advance Python `MtxRegimeAnalyzer`
  - build repeated snapshot payloads
- The current replay implementation also uses a full-resolution snapshot-frame path for chart requests, which is much heavier than a chart viewport actually needs.

Completed change:

- Split replay session semantics into:
  - `start` / `end`: initial viewport
  - `available_start` / `available_end`: replayable data coverage
- Added on-demand indicator extension so bars past the initial view no longer return empty indicator series.
- Fixed replay chart bootstrap so the frontend uses the explicit initial viewport and available bounds separately.
- Tightened `bundle-by-bars` bar search so `next` requests do not rescan from `session.start` and `prev` requests do not scan past `anchor`.

Files touched so far in this investigation:

- `src/qt_platform/option_power/replay.py`
- `src/qt_platform/cli/main.py`
- `src/qt_platform/storage/base.py`
- `src/qt_platform/storage/postgres_store.py`
- `src/qt_platform/storage/bar_store.py`
- `frontend/src/features/option-power/useOptionPowerReplay.ts`
- `frontend/src/features/option-power/types.ts`
- `frontend/src/features/option-power/useOptionPowerReplay.test.ts`
- `frontend/e2e/replay-ux.spec.ts`
- `tests/test_option_power_replay.py`

Tests/measurements run:

- `PYTHONPATH=src .venv/bin/pytest tests/test_option_power_replay.py tests/test_web_app.py` passed after replay range changes.
- `cd frontend && npm test -- --run src/features/option-power/useOptionPowerReplay.test.ts src/features/option-power/components/TimelineCharts.test.ts src/pages/OptionPowerResearchWorkspace.test.ts` passed.
- `cd frontend && npm run build` passed.
- Real replay API measurements on localhost:
  - hot path: `~157ms`
  - cold path beyond current materialized cache: `~26.1s`

Current implementation target:

- Add a chart-specific lightweight indicator materialization path for replay series queries.
- Materialize only requested interval boundary rows (`1m` / `5m` / `15m` / `30m`) instead of full 10-second snapshot frames.
- Keep session-aware state correctness by replaying only from the necessary session boundary, while still allowing multi-session windows.
- Continue using Polars for row-to-series derivation, but remove full snapshot construction from the viewport critical path.

Next concrete step:

- Implement the lightweight replay chart materializer and route `get_series_payload()` / `bundle-by-bars` interval requests through it, then measure the cold-path latency again on the real port-8000 service.

### 2026-04-30 Lightweight Chart Materializer Kickoff

Current implementation decision:

- Keep the existing full snapshot-frame path for snapshot APIs and full-resolution replay internals.
- Add a separate chart-only indicator path for interval requests (`1m` / `5m` / `15m` / `30m`).
- The chart path will:
  - replay only from the necessary session boundary
  - emit minimal indicator snapshots instead of full `MonitorSnapshot`
  - cache per-session chart interval rows separately from full frame cache

Reasoning:

- The current cold path spends most of its time in Python replay and full snapshot construction, not in Polars.
- Even after fixing bar-range scans, `bundle-by-bars` still pays for repeated `aggregator.snapshot(...).to_dict()` work when chart requests only need indicator rows.
- `build_indicator_series()` already accepts lightweight snapshot dicts, so the lowest-risk acceleration path is to reduce replay payload construction before the Polars stage.

Immediate implementation plan for this milestone:

- Add chart-specific interval caches onto `ReplaySession`.
- Add a lightweight replay materializer in `MonitorReplayService` that samples minute-boundary indicator rows and uses `MonitorAggregator.indicator_snapshot(...)`.
- Route `get_series_payload()` interval requests through the chart cache/materializer path.
- Add focused replay tests that prove interval series requests can populate from the lightweight cache without depending on full `frame_cache`.

Status:

- In progress: replay chart-only materialization refactor.

Completed change:

- Added a dedicated interval-series path in `MonitorReplayService.get_series_payload()`.
- Interval requests now bypass `_ensure_frames_for_window()` and the full `frame_cache` / full snapshot path.
- Added a chart-only materializer that:
  - replays from the relevant session boundary
  - emits interval bucket values using `MonitorAggregator.indicator_snapshot(...)`
  - skips `MtxRegimeAnalyzer` completely for pressure-only requests
  - skips IV surface work unless `iv_skew` is requested
- Added a dedicated per-session `chart_series_cache` for chart interval payload reuse.
- Added replay tests proving:
  - repeated interval window requests hit the chart cache
  - interval series can materialize even when background full-frame compute is disabled and `frame_cache` remains empty

Files touched in this segment:

- `src/qt_platform/option_power/replay.py`
- `tests/test_option_power_replay.py`
- `docs/POLARS_INDICATOR_BACKEND_PLAN.md`

Tests run:

- `PYTHONPATH=src .venv/bin/pytest tests/test_option_power_replay.py -q` passed (`14 passed`)
- `PYTHONPATH=src .venv/bin/python -m compileall -q src/qt_platform/option_power tests/test_option_power_replay.py` passed
- `PYTHONPATH=src .venv/bin/pytest tests/test_web_app.py -q` passed (`3 skipped`)
- `PYTHONPATH=src .venv/bin/pytest tests/test_option_power_indicator_backend.py -q` passed (`4 passed`)

Real replay measurements on a patched local replay server (`127.0.0.1:8012`):

- First `bundle-by-bars` request, `anchor=2026-04-27T13:45:00`, `direction=next`, `bar_count=50`, `interval=5m`, `names=pressure_index,raw_pressure`:
  - `~5.67s`
- First cold request on a new range, `anchor=2026-04-28T08:45:00`, same params:
  - `~7.84s`
- Immediate repeats of both cached interval windows:
  - `~0.09s`

Interpretation:

- The full-snapshot replay bottleneck is largely removed from chart interval requests.
- The remaining cold-path cost is now dominated by:
  - fetching and replaying raw option ticks for the requested session span
  - one-time interval-state materialization for a previously unseen range
- This is materially better than the prior `~26.1s`, but it is still not TradingView-grade cold latency.

Next concrete step:

- Add an incremental chart materializer state cache keyed by replay session window / interval so adjacent pan-right requests can extend existing replay state instead of rebuilding from the session boundary again.

### 2026-04-30 Incremental Chart State Checkpoints

Completed change:

- Added clone support for replay-time stateful engines:
  - `MonitorAggregator.clone()`
  - `MtxRegimeAnalyzer.clone()`
- Added `ChartStateCheckpoint` plus a per-session `chart_state_cache`.
- Updated the lightweight chart materializer so it can:
  - reuse the latest compatible checkpoint at or before the requested interval window
  - resume raw tick replay from `processed_until + 1 microsecond`
  - persist the final replay state after each chart materialization for the next adjacent request
- Kept checkpoint compatibility rules conservative:
  - pressure-only requests can reuse pressure-only or regime-capable checkpoints
  - regime-bearing requests only reuse checkpoints that already carry regime state
- Added replay coverage proving adjacent interval windows no longer restart from the full session boundary.

Files touched in this segment:

- `src/qt_platform/option_power/aggregator.py`
- `src/qt_platform/market_state/mtx.py`
- `src/qt_platform/option_power/replay.py`
- `tests/test_option_power_replay.py`
- `docs/POLARS_INDICATOR_BACKEND_PLAN.md`

Tests run:

- `PYTHONPATH=src .venv/bin/pytest tests/test_option_power_replay.py -q` passed (`15 passed`)
- `PYTHONPATH=src .venv/bin/python -m compileall -q src/qt_platform/option_power src/qt_platform/market_state/mtx.py tests/test_option_power_replay.py` passed
- `PYTHONPATH=src .venv/bin/pytest tests/test_web_app.py -q` passed (`3 skipped`)

Real replay measurements on a patched local replay server (`127.0.0.1:8013`):

- First `bundle-by-bars` request:
  - `anchor=2026-04-27T13:45:00`
  - `direction=next`
  - `bar_count=50`
  - `interval=5m`
  - `names=pressure_index,raw_pressure`
  - latency: `~1.53s`
- Adjacent follow-up request in the same night session:
  - `anchor=2026-04-27T19:05:00`
  - same remaining params
  - latency: `~2.74s`
- New uncached day-session request:
  - `anchor=2026-04-28T08:45:00`
  - same remaining params
  - latency: `~4.99s`
- Immediate repeat of cached windows:
  - `~0.088s`

Interpretation:

- Compared with the previous lightweight-only stage, first-seen interval windows improved again:
  - prior `~5.67s` window now `~1.53s`
  - prior `~7.84s` new-session cold window now `~4.99s`
- The remaining cold-path cost is now concentrated in:
  - fetching raw option ticks from storage for previously unseen ranges
  - replaying the raw tick slice needed to establish one new checkpoint
- Adjacent requests now benefit from resumed replay state instead of always starting from the session boundary, but they are still bounded by the tick volume in the newly requested segment.

Next concrete step:

- Reduce raw tick fetch cost for cold chart ranges by adding a storage-backed or in-memory tick slice cache for recent replay windows, then remeasure `bundle-by-bars` on the real service.

### 2026-04-30 Tick Slice Cache Experiment

Experiment:

- Tried adding a broader chart input cache for raw replay ticks / 1m bars so adjacent requests could avoid repeated DB reads.
- Initial version prefetched a much larger future session slice for chart requests.

Result:

- This did help adjacent requests materially, but it introduced an unacceptable regression on the first night-session request because the first viewport fetch paid for a much larger raw tick read upfront.
- That broader prefetch strategy was therefore rejected and backed out.

What remains in the code after rollback:

- The incremental replay-state checkpoint path remains in place.
- Exact-range chart input cache plumbing remains available, but broad lookahead prefetch is not enabled.

Current measured behavior on the latest patched local replay server (`127.0.0.1:8016`):

- `anchor=2026-04-27T13:45:00`, `next`, `50`, `5m`, `pressure_index,raw_pressure`:
  - `~5.60s`
- `anchor=2026-04-27T19:05:00`, same params:
  - `~7.00s`
- `anchor=2026-04-28T08:45:00`, same params:
  - `~5.81s`
- immediate repeats:
  - `~0.09s`

Interpretation:

- Replay-layer optimizations have removed the worst full-snapshot path and made exact-repeat windows very cheap.
- Further meaningful latency reduction now looks increasingly constrained by storage read cost and raw tick replay volume.
- The next serious speedup probably needs one of:
  - storage-side tick window caching / batching that is aware of replay usage
  - precomputed intraday chart frames
  - a coarser canonical option-power bar model for chart use

Next concrete step:

- Stop pushing replay-layer cache complexity upward and instead prototype a storage-facing raw tick window cache or precomputed chart-frame artifact, then compare that against the current `~5-7s` cold-path baseline.

- Finish installing dependencies with `.venv/bin/python -m pip install -e '.[dev]'`, rerun the focused Python tests with `pytest`, and run a small import check that confirms `indicator_backend.pl` is populated.
- Add a benchmark smoke test that builds backend series over a representative replay snapshot list and asserts runtime remains bounded.

### 2026-04-30

Completed change:

- Installed `polars 1.40.1` and project-compatible `pytest 8.4.2` in `.venv`.
- Verified the real Polars import path with `indicator_backend.pl is not None`.
- Added a benchmark smoke test that builds full backend indicator series over 1,440 synthetic replay snapshots.
- Added `indicator_series_to_context_extras()` and an `indicator_series` argument to `run_backtest()` so strategies can consume backend-computed canonical series via `StrategyContext.extras`.
- Added backtest coverage proving `signal_state` series can drive a strategy, and explicit `context_extras_by_ts` overrides generated series extras when both are supplied.
- Cleaned generated `src/qt_platform.egg-info/*` metadata noise from the working diff; `pyproject.toml` remains the dependency source of truth.

Files touched:

- `src/qt_platform/backtest/engine.py`
- `tests/test_backtest_engine.py`
- `tests/test_option_power_indicator_backend.py`
- `docs/POLARS_INDICATOR_BACKEND_PLAN.md`

Tests run:

- `PYTHONPATH=src .venv/bin/python - <<'PY' ...` import check passed and reported `polars_loaded True`, `polars_version 1.40.1`.
- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_option_power_indicator_backend.py tests/test_option_power_aggregator.py tests/test_option_power_replay.py` passed.
- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_option_power_indicator_backend.py -q` passed.
- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_backtest_engine.py tests/test_option_power_indicator_backend.py tests/test_option_power_aggregator.py tests/test_option_power_replay.py -q` passed.
- `PYTHONPATH=src .venv/bin/python -m compileall -q src/qt_platform/backtest src/qt_platform/option_power tests/test_backtest_engine.py tests/test_option_power_indicator_backend.py` passed.
- `npm test -- src/pages/OptionPowerResearchWorkspace.test.ts` passed.
- `npm run build` passed.
- `git diff --check` passed.

Known mismatch/blocker:

- Backtest can now consume canonical series if caller provides them, but there is not yet a CLI/service helper that builds option-power indicator series for a backtest date range directly from storage.

Next concrete step:

- Add a CLI or service helper that reuses replay/backend indicator construction to produce `indicator_series` for `run_backtest()` from stored option-power/MTX data.

Completed change:

- Added `MonitorReplayService.build_backtest_indicator_series()` as the storage-backed helper for producing canonical indicator series for backtests.
- Added opt-in CLI backtest flags:
  - `--with-option-power-indicators`
  - `--option-root`
  - `--expiry-count`
  - `--indicator-snapshot-interval-seconds`
  - `--indicator-series`
  - `--indicator-wait-timeout-seconds`
- Wired `_backtest()` so the helper output is passed into `run_backtest(..., indicator_series=...)` only when the opt-in flag is enabled.
- Added replay helper coverage and CLI coverage for both enabled and default-disabled indicator paths.

Files touched:

- `src/qt_platform/option_power/replay.py`
- `src/qt_platform/cli/main.py`
- `tests/test_option_power_replay.py`
- `tests/test_cli_backtest.py`
- `docs/POLARS_INDICATOR_BACKEND_PLAN.md`

Tests run:

- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_cli_backtest.py tests/test_backtest_engine.py tests/test_option_power_replay.py tests/test_option_power_indicator_backend.py -q` passed.
- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_cli_backtest.py tests/test_backtest_engine.py tests/test_option_power_replay.py tests/test_option_power_indicator_backend.py tests/test_option_power_aggregator.py -q` passed.
- `PYTHONPATH=src .venv/bin/python -m compileall -q src/qt_platform/cli src/qt_platform/backtest src/qt_platform/option_power tests/test_cli_backtest.py tests/test_backtest_engine.py tests/test_option_power_replay.py` passed.
- `PYTHONPATH=src .venv/bin/python -m qt_platform.cli.main backtest --help` passed.
- `npm test -- src/pages/OptionPowerResearchWorkspace.test.ts` passed.
- `npm run build` passed.
- `git diff --check` passed.

Known mismatch/blocker:

- The backtest CLI can now attach backend option-power indicators, but the built-in `sma-cross` strategy does not consume them. Users need a custom strategy or a future option-power-aware strategy definition to act on `signal_state` / `bias_signal`.

Next concrete step:

- Add an option-power-aware strategy definition that reads `StrategyContext.extras` / `BarCloseEvent.extras` and converts backend `signal_state` into orders under explicit risk constraints.

Completed change:

- Added `OptionPowerSignalStrategy` / `OptionPowerSignalLogic`.
- Strategy reads backend `signal_state` and `bias_signal` from `BarCloseEvent.extras`.
- Strategy only trades when target direction differs from current position, can require bias alignment, and exits on neutral by default.
- Added explicit `trade_size` and `max_position` risk controls via `FixedSizeExecutionPolicy`.
- Added CLI support for `--strategy option-power-signal`.
- Added CLI flags `--trade-size`, `--max-position`, `--no-bias-alignment`, and `--hold-through-neutral`.
- Made `--strategy option-power-signal` automatically build backend option-power indicators even without `--with-option-power-indicators`.

Files touched:

- `src/qt_platform/strategies/option_power_signal.py`
- `src/qt_platform/cli/main.py`
- `tests/test_option_power_signal_strategy.py`
- `tests/test_cli_backtest.py`
- `docs/POLARS_INDICATOR_BACKEND_PLAN.md`

Tests run:

- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_option_power_signal_strategy.py tests/test_cli_backtest.py tests/test_backtest_engine.py -q` passed.
- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_option_power_signal_strategy.py tests/test_cli_backtest.py tests/test_backtest_engine.py tests/test_option_power_replay.py tests/test_option_power_indicator_backend.py tests/test_option_power_aggregator.py -q` passed.
- `PYTHONPATH=src .venv/bin/python -m qt_platform.cli.main backtest --help` passed.
- `PYTHONPATH=src .venv/bin/python -m compileall -q src/qt_platform/strategies src/qt_platform/cli tests/test_option_power_signal_strategy.py tests/test_cli_backtest.py` passed.
- `npm test -- src/pages/OptionPowerResearchWorkspace.test.ts` passed.
- `npm run build` passed.

Known mismatch/blocker:

- `FixedSizeExecutionPolicy` reverses positions in bounded steps. If the strategy is long and backend signal flips short, the first sell closes the long position; a later still-short signal can open a short position.

Next concrete step:

- Run an end-to-end backtest command against a real stored window that has MTX bars plus option ticks, then compare fills/trades with the research UI signal timeline.

Completed change:

- Ran storage-backed end-to-end `option-power-signal` backtests against the configured Postgres database.
- Fixed replay session timezone normalization so aware CLI timestamps are converted to the repository/domain convention: Asia/Taipei naive datetimes.
- Added regression coverage that aware UTC replay inputs normalize to local domain time.
- Verified a no-signal short window completes without fills.
- Found a real signal window on `2026-04-16 08:45-09:45` Asia/Taipei and ran the strategy end-to-end.

Files touched:

- `src/qt_platform/option_power/replay.py`
- `tests/test_option_power_replay.py`
- `docs/POLARS_INDICATOR_BACKEND_PLAN.md`

Tests and commands run:

- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_option_power_replay.py tests/test_cli_backtest.py tests/test_option_power_signal_strategy.py -q` passed.
- `PYTHONPATH=src .venv/bin/python -m compileall -q src/qt_platform/option_power tests/test_option_power_replay.py` passed.
- `PYTHONPATH=src .venv/bin/python -m qt_platform.cli.main --config config/config.yaml backtest --symbol MTX --start 2026-04-30T00:45:00+00:00 --end 2026-04-30T01:04:00+00:00 --strategy option-power-signal --indicator-snapshot-interval-seconds 60 --indicator-wait-timeout-seconds 120 --indicator-series signal_state,bias_signal,raw_pressure,pressure_index,regime_state,structure_state --report-dir reports/e2e-option-power-signal` passed after timezone normalization. Result: 0 fills, 0 trades, net PnL 0.
- Scanned candidate Postgres windows and found nonzero backend `signal_state` on `2026-04-16 08:45-09:45` Asia/Taipei.
- `PYTHONPATH=src .venv/bin/python -m qt_platform.cli.main --config config/config.yaml backtest --symbol MTX --start 2026-04-16T08:45:00 --end 2026-04-16T09:45:00 --strategy option-power-signal --indicator-snapshot-interval-seconds 60 --indicator-wait-timeout-seconds 180 --indicator-series signal_state,bias_signal,raw_pressure,pressure_index,regime_state,structure_state --report-dir reports/e2e-option-power-signal-20260416` passed. Result: 4 fills, 2 trades, net PnL -49, ending position 0.

Known mismatch/blocker:

- End-to-end reports are generated under `reports/`; they are operational artifacts and not part of source changes.

Next concrete step:

- Add a compact report annotation or strategy metadata export that records the exact indicator values used for each option-power signal fill, making UI/backtest timeline comparisons easier.

Completed change:

- Added `metadata` to `Signal` and `Fill`.
- Preserved signal metadata through `FixedSizeExecutionPolicy`, `StrategyRuntime`, pending `next_open` fills, `same_bar` fills, and residual open fills after partial close handling.
- Added JSON report fill metadata serialization.
- Updated `OptionPowerSignalStrategy` metadata to include top-level decision fields plus an `indicator_values` map containing available canonical option-power indicator series for the signal timestamp.
- Verified the stored-window E2E backtest report now records per-fill indicator annotations, for example the first 2026-04-16 short fill includes `signal_state=-1`, `bias_signal=-1`, `pressure_index=0.0`, `raw_pressure=7.0`, `regime_state=-1`, and `structure_state=-1`.

Files touched:

- `src/qt_platform/domain.py`
- `src/qt_platform/strategies/base.py`
- `src/qt_platform/backtest/engine.py`
- `src/qt_platform/reporting/performance.py`
- `src/qt_platform/strategies/option_power_signal.py`
- `tests/test_backtest_engine.py`
- `tests/test_option_power_signal_strategy.py`
- `tests/test_reporting_performance.py`
- `docs/POLARS_INDICATOR_BACKEND_PLAN.md`

Tests and commands run:

- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_backtest_engine.py tests/test_option_power_signal_strategy.py tests/test_reporting_performance.py -q` passed.
- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_option_power_replay.py tests/test_cli_backtest.py tests/test_option_power_signal_strategy.py tests/test_backtest_engine.py tests/test_option_power_indicator_backend.py tests/test_option_power_aggregator.py tests/test_reporting_performance.py -q` passed.
- `PYTHONPATH=src .venv/bin/python -m qt_platform.cli.main --config config/config.yaml backtest --symbol MTX --start 2026-04-16T08:45:00 --end 2026-04-16T09:45:00 --strategy option-power-signal --indicator-snapshot-interval-seconds 60 --indicator-wait-timeout-seconds 180 --indicator-series signal_state,bias_signal,raw_pressure,pressure_index,regime_state,structure_state --report-dir reports/e2e-option-power-signal-20260416` passed. Result: 4 fills, 2 trades, net PnL -49, ending position 0, fill metadata present in JSON report.
- `git diff --check` passed.

Known mismatch/blocker:

- Report annotations include whichever canonical indicator series were requested/built for the backtest. To compare more fields with the UI timeline, pass a broader `--indicator-series` list or omit it once a default full-series report workflow is desired.

Next concrete step:

- Add a small report or CLI summary mode that can print/export the annotated option-power fills as a compact table for UI timeline comparison without opening the full JSON report.

Completed change:

- Added `build_annotated_fill_summary_rows()` and `write_annotated_fill_summary_csv()`.
- The compact CSV flattens each fill with decision fields and common option-power indicator columns: `signal_state`, `bias_signal`, target/bias direction, pressure, regime, structure, trend quality, flow, and range fields.
- Added `--fill-summary-csv` for any backtest strategy.
- Made `--strategy option-power-signal` automatically write `{symbol}-backtest-fills.csv` next to the HTML/JSON reports.
- Verified the stored-window E2E command now prints `fill_summary_csv=reports/e2e-option-power-signal-20260416/MTX-backtest-fills.csv`, and the CSV contains the four annotated fills from 2026-04-16.

Files touched:

- `src/qt_platform/reporting/performance.py`
- `src/qt_platform/cli/main.py`
- `tests/test_reporting_performance.py`
- `tests/test_cli_backtest.py`
- `docs/POLARS_INDICATOR_BACKEND_PLAN.md`

Tests and commands run:

- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_reporting_performance.py tests/test_cli_backtest.py -q` passed.
- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_option_power_replay.py tests/test_cli_backtest.py tests/test_option_power_signal_strategy.py tests/test_backtest_engine.py tests/test_option_power_indicator_backend.py tests/test_option_power_aggregator.py tests/test_reporting_performance.py -q` passed.
- `PYTHONPATH=src .venv/bin/python -m compileall -q src/qt_platform/cli src/qt_platform/reporting src/qt_platform/backtest src/qt_platform/strategies tests/test_cli_backtest.py tests/test_reporting_performance.py` passed.
- `PYTHONPATH=src .venv/bin/python -m qt_platform.cli.main backtest --help` passed and lists `--fill-summary-csv`.
- `PYTHONPATH=src .venv/bin/python -m qt_platform.cli.main --config config/config.yaml backtest --symbol MTX --start 2026-04-16T08:45:00 --end 2026-04-16T09:45:00 --strategy option-power-signal --indicator-snapshot-interval-seconds 60 --indicator-wait-timeout-seconds 180 --indicator-series signal_state,bias_signal,raw_pressure,pressure_index,regime_state,structure_state --report-dir reports/e2e-option-power-signal-20260416` passed. Result: 4 fills, 2 trades, net PnL -49, and CSV export present.

Known mismatch/blocker:

- The CSV shows blanks for fields not requested in `--indicator-series`. This is expected for narrow E2E runs; omit `--indicator-series` or include the needed names when comparing more panels with the UI.

Next concrete step:

- Decide whether the remaining frontend parity helper functions should stay as test fixtures or be removed after tests move to backend/API fixtures.

Completed change:

- Removed unused frontend decision-grade derivation helpers from `OptionPowerResearchWorkspace.tsx`: signal, bias, trend quality, trend bias, flow impulse, flow state, range state, pressure-side helpers, rolling-window helpers, and clamp/quantile helpers.
- Added exported `OPTION_POWER_RESEARCH_SERIES` so the research page series contract is explicit and testable.
- Replaced the frontend formula unit tests with a contract test that verifies the UI requests backend-derived decision series.
- Kept parity/formula coverage in backend tests, where the canonical formulas now live.

Files touched:

- `frontend/src/pages/OptionPowerResearchWorkspace.tsx`
- `frontend/src/pages/OptionPowerResearchWorkspace.test.ts`
- `docs/POLARS_INDICATOR_BACKEND_PLAN.md`

Tests and commands run:

- `rg -n "deriveSignalStateValue|deriveBiasValue|resolvePressureSide|resolvePressureSlope|deriveSignalSeries|deriveBiasSeries|deriveTrendQualitySeries|deriveTrendBiasSeries|deriveFlowImpulseSeries|deriveFlowStateSeries|deriveRangeStateSeries|rollingQuantile|rollingWindowValues|clampNumber|pressureSupportsBias" frontend/src tests frontend -g '*.{ts,tsx,js,jsx}'` returned no matches.
- `npm test -- src/pages/OptionPowerResearchWorkspace.test.ts` from `frontend/` passed.
- `npm run build` from `frontend/` passed.
- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_option_power_indicator_backend.py tests/test_option_power_replay.py tests/test_cli_backtest.py tests/test_backtest_engine.py tests/test_reporting_performance.py -q` passed.

Known mismatch/blocker:

- The root repository has no `package.json`, so frontend npm commands must be run from `frontend/`.

Next concrete step:

- Run one final combined verification pass and prepare the implementation for Claude code review.

Completed change:

- Ran the final combined verification pass for backend, CLI, and frontend changes.
- Confirmed the backtest help output includes `--fill-summary-csv`.
- Confirmed diff whitespace checks pass.

Files touched:

- `docs/POLARS_INDICATOR_BACKEND_PLAN.md`

Tests and commands run:

- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_option_power_replay.py tests/test_cli_backtest.py tests/test_option_power_signal_strategy.py tests/test_backtest_engine.py tests/test_option_power_indicator_backend.py tests/test_option_power_aggregator.py tests/test_reporting_performance.py -q` passed.
- `npm test -- src/pages/OptionPowerResearchWorkspace.test.ts` from `frontend/` passed.
- `npm run build` from `frontend/` passed.
- `PYTHONPATH=src .venv/bin/python -m qt_platform.cli.main backtest --help` passed and lists `--fill-summary-csv`.
- `git diff --check` passed.

Known mismatch/blocker:

- None for the implemented phase. Remaining operational artifacts are generated under ignored `reports/`.

Next concrete step:

- Hand the implementation to Claude code review.

Completed change:

- Investigated replay UX feedback where `serve-option-power-replay --start 2026-04-27T08:45:00 --end 2026-04-27T13:45:00` opened with 08:45 shifted right and immediately requested an older blank window.
- Confirmed the configured Postgres data has raw ticks and MTX bars for both `2026-04-27 08:45-13:45` and the accidentally requested `2026-04-24 20:40-23:40` window; backend replay can compute non-empty `raw_pressure`, `pressure_index`, and `signal_state` 5m series for both windows.
- Fixed the frontend replay chart bootstrap so initial render sets the visible range to the loaded replay bars and ignores visible-range events until after the initial fit is complete. This prevents bootstrap whitespace from auto-extending the replay session and asking the API for unrelated dates.

Files touched:

- `frontend/src/features/option-power/components/TimelineCharts.tsx`
- `docs/POLARS_INDICATOR_BACKEND_PLAN.md`

Tests and commands run:

- `PYTHONPATH=src .venv/bin/python - <<'PY' ...` checked DB/replay payload counts for `2026-04-27 08:45-13:45` and `2026-04-24 20:40-23:40`; both returned non-empty backend series after compute readiness.
- `npm test -- src/features/option-power/components/TimelineCharts.test.ts src/features/option-power/useOptionPowerReplay.test.ts src/pages/OptionPowerResearchWorkspace.test.ts` from `frontend/` passed.
- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_option_power_replay.py tests/test_option_power_indicator_backend.py -q` passed.
- `npm run build` from `frontend/` passed.

Known mismatch/blocker:

- Could not curl the user's exact localhost `5173` session from this shell because the dev server was not reachable here. The same windows were verified directly through the configured store and replay service.
- Empty series during replay startup can still appear temporarily for a requested window that background compute has not reached yet; the frontend reloads the loaded window after readiness. The fixed bootstrap path should stop the wrong 04/24 window from being requested in the first place.

Next concrete step:

- Re-test `serve-option-power-replay` in the browser with the `2026-04-27 08:45-13:45` window and confirm the first visible bar is 08:45 with no automatic request before the configured start.

Completed change:

- Re-scoped the replay UX/performance plan around data layering rather than only Polars formula execution.
- Accepted the main architectural direction: compute/cache indicators once at full resolution, then serve visible-range slices with optional viewport downsampling.
- Defined the next milestones: Level 1 session indicator cache, response coverage metadata, viewport point-count downsampling, frontend buffered visible-range cache, and finer async readiness events.

Files touched:

- `docs/POLARS_INDICATOR_BACKEND_PLAN.md`

Tests and commands run:

- Not run; documentation-only planning update.

Known mismatch/blocker:

- Current replay API still rebuilds indicator series on cache miss and does not expose served/computed coverage or target point count.

Next concrete step:

- Implement replay Level 1 full-resolution indicator cache and make `get_series_payload()` slice that cache instead of rebuilding indicators per window.

Completed change:

- Added replay Level 1 indicator cache fields to each `ReplaySession`: full-resolution canonical series, cache start/end, and frame count.
- Changed `get_series_payload()` to build/update the session indicator cache once per frame-cache version and serve range slices from it, instead of rebuilding indicator series for every requested window.
- Added series `coverage` metadata to replay `/series` and `/bundle` style responses, including requested range, expanded query range, computed coverage, completion state, frame count, and target point budget.
- Added focused regression coverage proving subsequent series slices reuse the session indicator cache.

Files touched:

- `src/qt_platform/option_power/replay.py`
- `tests/test_option_power_replay.py`
- `docs/POLARS_INDICATOR_BACKEND_PLAN.md`

Tests and commands run:

- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_option_power_replay.py tests/test_web_app.py -q` passed with skips for unavailable FastAPI test client cases where applicable.

Known mismatch/blocker:

- Cache is still process-local and replay-session-local; there is no persistent Parquet/DB cache or raw-data version key yet.
- During active background compute, the L1 cache updates when queried and frame count changes; finer range-ready events are still pending.

Next concrete step:

- Add viewport target point count support so range queries can return chart-sized slices instead of full-resolution series.

Completed change:

- Added optional `max_points` support to replay `get_bars()`, `get_series_payload()`, `get_bundle()`, and `get_bundle_by_bars()`.
- Added API query support for `max_points` on replay bars, series, bundle, and bundle-by-bars endpoints.
- Implemented simple server-side downsampling:
  - bars use OHLCV bucket aggregation;
  - state/signal series use last value per bucket;
  - numeric indicator series use average value per bucket.
- Added frontend API parameters for replay bundle calls and made replay requests send a conservative point budget based on viewport width, capped at 2,400 points.
- Changed replay chart `viewKey` to use session id and interval instead of loaded window start/end, so adding new chunks does not recreate the chart and reset the user's view.
- Added focused test coverage for `max_points` and coverage metadata.

Files touched:

- `src/qt_platform/option_power/replay.py`
- `src/qt_platform/web/app.py`
- `frontend/src/features/option-power/api.ts`
- `frontend/src/features/option-power/types.ts`
- `frontend/src/features/option-power/useOptionPowerReplay.ts`
- `frontend/src/features/option-power/useOptionPowerReplay.test.ts`
- `frontend/src/pages/OptionPowerResearchWorkspace.tsx`
- `tests/test_option_power_replay.py`
- `tests/test_web_app.py`
- `docs/POLARS_INDICATOR_BACKEND_PLAN.md`

Tests and commands run:

- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_option_power_replay.py tests/test_web_app.py tests/test_cli_backtest.py -q` passed.
- `npm test -- src/features/option-power/useOptionPowerReplay.test.ts src/features/option-power/components/TimelineCharts.test.ts src/pages/OptionPowerResearchWorkspace.test.ts` from `frontend/` passed.
- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_option_power_replay.py tests/test_web_app.py tests/test_cli_backtest.py tests/test_backtest_engine.py tests/test_option_power_indicator_backend.py tests/test_option_power_aggregator.py tests/test_reporting_performance.py -q` passed.
- `PYTHONPATH=src .venv/bin/python -m compileall -q src/qt_platform/option_power src/qt_platform/web tests/test_option_power_replay.py tests/test_web_app.py` passed.
- `npm run build` from `frontend/` passed.
- `git diff --check` passed.

Known mismatch/blocker:

- Frontend still does not maintain a full buffered visible-range cache; it sends a point budget but still merges into the existing replay hook state.
- The downsampling policy is intentionally simple and should become per-indicator configurable before adding more indicator families such as bands.

Next concrete step:

- Run build/full affected verification, then continue with frontend buffered visible-range cache and finer async range-ready events.

Completed change:

- Added frontend visible-range buffer logic to replay loading. Pan/zoom requests are expanded by 20% on both sides, clamped to the current session, and skipped when the buffered range is already covered by loaded data.
- Preserved existing session-extension behavior when the user genuinely pans outside the current replay session.
- Added a regression test proving a visible range already covered by the loaded buffer does not issue another replay bundle request.
- Expanded replay SSE events with `range_ready`, emitted whenever `computed_until` advances. The event includes session id, session start, ready end, computed_until, and compute status.
- Updated the replay hook to listen for `range_ready`; if the current loaded window was partial, it refetches that loaded window as soon as compute coverage reaches it instead of waiting for full session readiness.

Files touched:

- `src/qt_platform/web/app.py`
- `frontend/src/features/option-power/useOptionPowerReplay.ts`
- `frontend/src/features/option-power/useOptionPowerReplay.test.ts`
- `docs/POLARS_INDICATOR_BACKEND_PLAN.md`

Tests and commands run:

- `npm test -- src/features/option-power/useOptionPowerReplay.test.ts` from `frontend/` passed.
- `npm test -- src/features/option-power/useOptionPowerReplay.test.ts src/features/option-power/components/TimelineCharts.test.ts src/pages/OptionPowerResearchWorkspace.test.ts` from `frontend/` passed.
- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_web_app.py tests/test_option_power_replay.py -q` passed with skipped FastAPI client cases where unavailable.
- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_option_power_replay.py tests/test_web_app.py tests/test_cli_backtest.py tests/test_backtest_engine.py tests/test_option_power_indicator_backend.py tests/test_option_power_aggregator.py tests/test_reporting_performance.py -q` passed.
- `PYTHONPATH=src .venv/bin/python -m compileall -q src/qt_platform/web src/qt_platform/option_power tests/test_web_app.py tests/test_option_power_replay.py` passed.
- `npm run build` from `frontend/` passed.
- `git diff --check` passed.

Known mismatch/blocker:

- Frontend cache is still represented as one merged loaded range. It does not yet track multiple disjoint cached ranges or per-series coverage.
- `range_ready` is coarse: it indicates session compute coverage through `computed_until`, not a per-request/per-series readiness event.

Next concrete step:

- Add multi-range frontend coverage tracking or backend request IDs if pan/zoom patterns show disjoint ranges are common.

Completed change:

- Added `loadedRanges` to the replay hook so frontend coverage is tracked as multiple loaded ranges instead of a single outer `loadedStart` / `loadedEnd` span.
- Updated replay load and cursor prefetch paths to merge incoming coverage into `loadedRanges`, while keeping `loadedStart` / `loadedEnd` as compatibility/display bounds.
- Changed visible-range fetch decisions to use range containment. A buffered visible range is only considered loaded if one existing loaded range fully covers it; gaps between disjoint ranges are no longer treated as loaded.
- Added a regression test that loads two disjoint ranges, confirms a visible range inside the second loaded range does not refetch, and confirms a visible range in the gap does refetch.

Files touched:

- `frontend/src/features/option-power/useOptionPowerReplay.ts`
- `frontend/src/features/option-power/useOptionPowerReplay.test.ts`
- `docs/POLARS_INDICATOR_BACKEND_PLAN.md`

Tests and commands run:

- `npm test -- src/features/option-power/useOptionPowerReplay.test.ts` from `frontend/` passed.
- `npm test -- src/features/option-power/useOptionPowerReplay.test.ts src/features/option-power/components/TimelineCharts.test.ts src/pages/OptionPowerResearchWorkspace.test.ts` from `frontend/` passed.
- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_web_app.py tests/test_option_power_replay.py -q` passed with skipped FastAPI client cases where unavailable.
- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_option_power_replay.py tests/test_web_app.py tests/test_cli_backtest.py tests/test_backtest_engine.py tests/test_option_power_indicator_backend.py tests/test_option_power_aggregator.py tests/test_reporting_performance.py -q` passed.
- `npm run build` from `frontend/` passed.
- `git diff --check` passed.

Known mismatch/blocker:

- `loadedRanges` is still shared for bars and all requested series. It does not yet track per-series coverage or per-interval coverage beyond resetting on interval changes.
- Cursor prefetch still uses bar-count based endpoints for edge loading; exact visible-range slice loading handles gaps inside the loaded bounds.

Next concrete step:

- If needed after browser testing, split frontend coverage into `barsCoverage` and `seriesCoverageByName` and add backend request IDs for precise `range_ready` refetches.

Completed change:

- Split frontend replay coverage further into:
  - `loadedRanges` for fetched bar/data windows;
  - `seriesLoadedRanges` for completed indicator series windows;
  - `seriesPendingRanges` for windows whose bundle returned partial series because backend compute had not covered them yet.
- Partial replay bundle responses now mark their range as pending instead of treating series as complete.
- `range_ready` handling now refetches pending ranges that have become computable instead of reloading the full outer loaded bounds.
- Added a request-id contract for replay series/bundle requests:
  - frontend replay bundle requests send generated `request_id` values;
  - backend echoes `request_id` in series coverage metadata;
  - tests verify request id propagation through coverage.
- Added a regression test proving pending series ranges are not repeatedly requested while compute is still pending.

Files touched:

- `src/qt_platform/option_power/replay.py`
- `src/qt_platform/web/app.py`
- `frontend/src/features/option-power/api.ts`
- `frontend/src/features/option-power/types.ts`
- `frontend/src/features/option-power/useOptionPowerReplay.ts`
- `frontend/src/features/option-power/useOptionPowerReplay.test.ts`
- `tests/test_option_power_replay.py`
- `tests/test_web_app.py`
- `docs/POLARS_INDICATOR_BACKEND_PLAN.md`

Tests and commands run:

- `npm test -- src/features/option-power/useOptionPowerReplay.test.ts` from `frontend/` passed.
- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_option_power_replay.py tests/test_web_app.py -q` passed with skipped FastAPI client cases where unavailable.
- `npm test -- src/features/option-power/useOptionPowerReplay.test.ts src/features/option-power/components/TimelineCharts.test.ts src/pages/OptionPowerResearchWorkspace.test.ts` from `frontend/` passed.
- `PYTHONPATH=src .venv/bin/python -m pytest tests/test_option_power_replay.py tests/test_web_app.py tests/test_cli_backtest.py tests/test_backtest_engine.py tests/test_option_power_indicator_backend.py tests/test_option_power_aggregator.py tests/test_reporting_performance.py -q` passed.
- `PYTHONPATH=src .venv/bin/python -m compileall -q src/qt_platform/web src/qt_platform/option_power tests/test_web_app.py tests/test_option_power_replay.py` passed.
- `npm run build` from `frontend/` passed.
- `git diff --check` passed.

Known mismatch/blocker:

- Coverage is split between completed and pending ranges, but still shared across all requested indicator names. A future refinement can track `seriesCoverageByName` if different panels request different indicator subsets.
- `range_ready` still reflects compute progress by time, not a specific backend job queue with durable request ids.

Next concrete step:

- Browser-test replay pan/zoom on a large real window, then decide whether per-series coverage or backend priority compute queue is the next bottleneck.

Completed change:

- Added Playwright browser-test infrastructure under `frontend/`.
- Added `npm run test:e2e` for browser smoke tests.
- Added `frontend/e2e/replay-ux.spec.ts`, which mocks replay APIs and verifies:
  - replay page boots with rendered chart canvas;
  - the first bundle request starts exactly at the configured replay session start;
  - the initial request uses the expected 3-hour replay window;
  - replay bundle requests include `max_points` and generated `request_id`;
  - wheel/pan-driven requests do not request bundle ranges before the session start.
- Added stable chart container `data-testid` attributes for browser automation.
- Pinned Playwright to `@playwright/test@1.42.1` because the local Node runtime is `v18.14.2`; newer Playwright releases require Node `18.19+`.
- Installed the matching Chromium browser locally with `npx playwright install chromium`.

Files touched:

- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/playwright.config.ts`
- `frontend/e2e/replay-ux.spec.ts`
- `frontend/src/features/option-power/components/TimelineCharts.tsx`
- `docs/POLARS_INDICATOR_BACKEND_PLAN.md`

Tests and commands run:

- `npm run test:e2e` from `frontend/` passed.
- `npm test -- src/features/option-power/components/TimelineCharts.test.ts src/features/option-power/useOptionPowerReplay.test.ts src/pages/OptionPowerResearchWorkspace.test.ts` from `frontend/` passed.
- `npm run build` from `frontend/` passed.

Known mismatch/blocker:

- This browser smoke test uses mocked replay APIs so it is deterministic and does not require the real TimescaleDB dataset.
- It catches request-shape and chart-bootstrap regressions, but it does not replace a final manual feel check against real `serve-option-power-replay` data.
- Playwright is pinned below latest only to match the current local Node version. When Node is upgraded to `18.19+` or newer, Playwright should be upgraded.

Next concrete step:

- Run the same browser workflow against a real replay server window to compare perceived smoothness and decide whether the next backend step should be per-series coverage tracking or a priority compute queue.

Completed change:

- Tightened the replay browser smoke test after manual feedback showed the first version missed an idle-load loop.
- The Playwright test now waits after initial render and asserts the replay page stays at exactly one initial bundle request while the user does nothing.
- The strengthened test reproduced three duplicate initial bundle requests before the fix.
- Added frontend in-flight de-duplication for identical replay bundle loads keyed by series set, session id, interval, start, and end.
- Suppressed replay visible-range callbacks while `TimelineCharts` performs programmatic chart range changes during bootstrap, live auto-follow, and range restore after `setData()`.
- Switched replay visible-range resolution to read from a current normalized-data ref so callbacks do not use stale bootstrap data.

Files touched:

- `frontend/e2e/replay-ux.spec.ts`
- `frontend/src/features/option-power/components/TimelineCharts.tsx`
- `frontend/src/features/option-power/useOptionPowerReplay.ts`
- `docs/POLARS_INDICATOR_BACKEND_PLAN.md`

Tests and commands run:

- `npm run test:e2e` from `frontend/` passed after reproducing and fixing the idle duplicate-load loop.
- `npm test -- src/features/option-power/useOptionPowerReplay.test.ts src/features/option-power/components/TimelineCharts.test.ts` from `frontend/` passed.
- `npm run build` from `frontend/` passed.

Known mismatch/blocker:

- The smoke test still uses mocked replay data. It now catches idle request loops, but final acceptance should still include one real `serve-option-power-replay` session.

Next concrete step:

- Re-test manually with `serve-option-power-replay`; if the chart still moves while idle, instrument visible-range callback payloads and compare them with backend request ids.

Completed change:

- Removed automatic replay-session expansion from frontend visible-range handling.
- Visible-range callbacks now only request slices/prefetches inside the current replay session. They no longer call `createReplaySession()` when chart whitespace or restore math produces a range outside the current session.
- Strengthened Playwright coverage to fail if opening the replay page or wheel/pan behavior triggers `/api/option-power/replay/sessions?...` session creation.
- Updated hook unit tests to encode the new rule: replay session boundaries are explicit and are not expanded by chart viewport callbacks.

Files touched:

- `frontend/src/features/option-power/useOptionPowerReplay.ts`
- `frontend/src/features/option-power/useOptionPowerReplay.test.ts`
- `frontend/e2e/replay-ux.spec.ts`
- `docs/POLARS_INDICATOR_BACKEND_PLAN.md`

Tests and commands run:

- `npm run test:e2e` from `frontend/` passed.
- `npm test -- src/features/option-power/useOptionPowerReplay.test.ts src/features/option-power/components/TimelineCharts.test.ts` from `frontend/` passed.
- `npm run build` from `frontend/` passed.

Known mismatch/blocker:

- A stale browser tab or already-running backend can still have an old oversized replay session computing in the background. Restart the replay server after this frontend fix when validating manually.
- Backend still accepts large replay sessions if directly requested. A future hardening step should add server-side max session duration / cancellation for UI replay sessions.

Next concrete step:

- Add backend guardrails for replay session creation: maximum UI replay span, cancellation for superseded sessions, and explicit status for background compute saturation.

Completed change:

- Fixed visible-range prefetch after removing automatic session expansion.
- Empty chart whitespace inside the current replay session now triggers bounded cursor prefetch:
  - right-side whitespace requests `bundle-by-bars` with `direction=next`;
  - left-side whitespace requests `bundle-by-bars` with `direction=prev`.
- The prefetch decision now uses the nearest loaded range around the visible/buffered range instead of only the global loaded start/end. This matters when the frontend has multiple disjoint cached ranges.
- Added unit coverage for both left and right whitespace prefetch while still asserting no larger replay session is created.

Files touched:

- `frontend/src/features/option-power/useOptionPowerReplay.ts`
- `frontend/src/features/option-power/useOptionPowerReplay.test.ts`
- `docs/POLARS_INDICATOR_BACKEND_PLAN.md`

Tests and commands run:

- `npm test -- src/features/option-power/useOptionPowerReplay.test.ts` from `frontend/` passed.
- `npm run test:e2e` from `frontend/` passed.
- `npm run build` from `frontend/` passed.

Known mismatch/blocker:

- Current Playwright coverage still does not simulate a real drag into whitespace; the hook-level tests now cover the intended request behavior directly.

Next concrete step:

- Add a Playwright drag/pan case that asserts `bundle-by-bars` is called for in-session whitespace without calling replay session creation.

## Resume Notes

- Start by reading this file, then inspect `src/qt_platform/option_power/indicator_backend.py`, `src/qt_platform/backtest/engine.py`, `src/qt_platform/strategies/option_power_signal.py`, and `src/qt_platform/cli/main.py`.
- Frontend decision-grade helper formulas have been removed; backend `indicator_backend.py` is the canonical formula source.
- `frontend/src/pages/OptionPowerResearchWorkspace.tsx` exports `OPTION_POWER_RESEARCH_SERIES` as the UI/API series contract.
- Backtest consumes canonical indicator series through the new `indicator_series` argument on `run_backtest()`.
- CLI backtest can build those series from storage with `--with-option-power-indicators`; it remains disabled by default.
- `--strategy option-power-signal` automatically enables storage-backed option-power indicator construction.
- Replay chart bootstrap now sets the initial visible range from loaded bars and suppresses bootstrap visible-range callbacks, avoiding accidental session extension before the configured replay start.
- Browser UX coverage exists via `cd frontend && npm run test:e2e`; it uses mocked replay APIs and requires the Playwright Chromium browser installed for the pinned Playwright version.
- Replay UX refactor direction is now: L1 full-resolution indicator cache, visible-range slice, viewport downsample, then frontend buffered cache and range-ready async events.
- If parity changes are needed, update backend helper tests first, then adjust the frontend series contract only when the backend API names change.
