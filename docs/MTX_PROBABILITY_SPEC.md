# MTX Kronos Probability Strategy Spec

## 1. Goal

Build a new MTX intraday strategy family that treats Kronos as a probabilistic indicator source, not as a direct price forecast.

Primary first target:

- `mtx_up_50_in_10m_probability`
- `mtx_down_50_in_10m_probability`

Interpretation:

- At each completed MTX 1m bar, use recent 1m K bars as model context.
- Ask Kronos to generate multiple future paths for the next 10 bars.
- Convert those raw paths into hit probabilities:
  - up hit: any future high reaches `current_close + 50`
  - down hit: any future low reaches `current_close - 50`

This should become a strategy-facing indicator series that is evaluated on its own first. Existing option-power and regime fields such as `chop_score`, `pressure_index`, and `raw_pressure` are research/reference overlays for manual review, not first-version strategy gates.

## 2. Current Repository Fit

The current backtest path already has the right extension seam:

1. `src/qt_platform/backtest/engine.py` accepts `indicator_series`.
2. `indicator_series_to_context_extras()` maps `{name: [{time, value}]}` into `BarCloseEvent.extras`.
3. The backtest engine already supports indicator values flowing through `context.event.extras`.

Recommended integration pattern:

- Add a Kronos probability indicator builder that emits the same `indicator_series` shape as option-power replay.
- Add a separate MTX probability strategy that reads probability fields from extras.
- Do not make the core strategy call Kronos directly in the first implementation. Model inference should be outside the strategy decision logic so backtest, replay, caching, and live operation can share the same contract.
- Do not depend on legacy bias/signal fields. Those series were removed from the codebase and are not part of the Kronos strategy contract.

## 3. Kronos Constraint

`Kronos/model/kronos.py` currently averages generated samples before returning:

- `auto_regressive_inference()` reshapes decoded output to `(batch, sample_count, seq_len, features)`.
- It then performs `np.mean(preds, axis=1)`.
- `KronosPredictor.predict()` therefore returns only an averaged forecast path.

That is not sufficient for probability indicators because the distribution and path-level extrema are lost.

Required low-level extension:

- Add a project-owned raw path inference wrapper instead of changing the ignored vendored `Kronos/` source.
- Preserve existing default Kronos behavior for normal averaged forecasts.
- Return raw paths with a stable shape before averaging.

Proposed shape after inverse normalization:

```text
single series: (sample_count, pred_len, 6)
batch series:  (batch, sample_count, pred_len, 6)
features:      open, high, low, close, volume, amount
```

## 4. Proposed Modules

### 4.1 Kronos adapter

New package:

```text
src/qt_platform/kronos/
```

Suggested files:

- `adapter.py`: loads tokenizer/model, owns device selection, exposes `predict_paths(...)`.
- `features.py`: converts `Bar` objects to Kronos input DataFrame and future timestamps.
- `probability.py`: computes event probabilities from raw paths.
- `raw_inference.py`: mirrors Kronos autoregressive inference but keeps the `sample_count` path dimension.
- `series.py`: builds storage/backtest indicator series over a bar window.

Keep the vendored `Kronos/` directory isolated. The project adapter should hide Kronos import path details and optional dependencies from the rest of `qt_platform`.

### 4.2 Probability calculator

Initial probability metrics use generated names from configurable targets:

```text
mtx_up_50_in_10m_probability
mtx_down_50_in_10m_probability
mtx_expected_close_delta_10m
mtx_path_close_delta_p10_10m
mtx_path_close_delta_p50_10m
mtx_path_close_delta_p90_10m
mtx_probability_sample_count
mtx_probability_ready
```

The first target is `10m + 50 points`, but the calculator should accept a list of targets:

```text
ProbabilityTarget(minutes=10, points=50)
ProbabilityTarget(minutes=30, points=100)
```

Generated field naming:

```text
mtx_up_{points}_in_{minutes}m_probability
mtx_down_{points}_in_{minutes}m_probability
```

This keeps future experiments like `30m + 100 points` as config changes instead of new indicator implementations.

Initial formulas per target:

```python
target_paths = paths[:, :horizon_steps, :]
up_success = (target_paths[:, :, high_idx] >= current_close + points).any(axis=1)
down_success = (target_paths[:, :, low_idx] <= current_close - points).any(axis=1)
up_probability = float(up_success.mean())
down_probability = float(down_success.mean())
```

Important detail:

- Use `current_close` from the last real input bar, not from the first predicted open.
- Validate predicted high/low consistency defensively because generated OHLC can be structurally imperfect.
- Set Kronos `pred_len` to the maximum requested target horizon. Multiple probability targets can then be computed from one raw path batch.
- Longer horizons increase inference cost because autoregressive generation runs one step at a time. The code design can be flexible without much complexity, but live latency must be measured separately for targets such as `30m + 100 points`.

## 5. Backtest Data Flow

Recommended first implementation is offline/backtest-only:

1. Load MTX 1m bars from storage.
2. For each decision timestamp with enough lookback:
   - take the last `lookback` bars.
   - generate raw Kronos paths for `pred_len`.
   - compute probabilities.
   - emit indicator points at the current bar timestamp.
3. Pass the resulting series into `run_backtest(..., indicator_series=...)`.
4. Strategy reads the probability fields from `BarCloseEvent.extras`.

Implemented CLI surface:

```text
qt-platform build-mtx-probability-series \
  --symbol MTX \
  --start 2026-04-13T00:00:00 \
  --end 2026-04-16T13:45:00 \
  --history-start 2026-04-01T00:00:00 \
  --lookback 256 \
  --stride 1 \
  --max-decisions 100 \
  --target 10m:50 \
  --sample-count 64 \
  --model NeoQuasar/Kronos-mini \
  --tokenizer NeoQuasar/Kronos-Tokenizer-2k \
  --output reports/mtx-probability-series.json
```

Output shape:

```json
{
  "metadata": {
    "symbol": "MTX",
    "timeframe": "1m",
    "history_start": "2026-04-01T00:00:00",
    "start": "2026-04-13T00:00:00",
    "end": "2026-04-16T13:45:00",
    "lookback": 256,
    "stride": 1,
    "max_decisions": 100,
    "targets": ["10m:50"],
    "series_names": ["mtx_up_50_in_10m_probability"]
  },
  "series": {
    "mtx_up_50_in_10m_probability": [{"time": "...", "value": 0.72}]
  }
}
```

`--start` and `--end` define the decision timestamps to emit. `--history-start` is optional and only controls how far back bars are loaded for lookback context. For example, replaying `2026-04-11` through `2026-04-30` can load bars from `2025-04-01` while emitting probability points only from `2026-04-11` onward. The CLI still runs Kronos once per emitted decision timestamp when `--stride 1`; it does not require manually launching one command per minute.

Deferred backtest surface:

```text
qt-platform backtest \
  --symbol MTX \
  --start ... \
  --end ... \
  --strategy mtx-probability \
  --with-mtx-probability \
  --kronos-lookback 256 \
  --kronos-sample-count 64 \
  --kronos-target 10m:50
```

For early research, prefer a separate build command and JSON cache first. Inline backtest inference can come later after latency is understood.

The CLI should allow repeated targets later:

```text
--target 10m:50 --target 30m:100
```

## 5.1 Initial Data Scope

Use the local DB as the first research source:

- primary symbol: `MTX`
- first detailed window: start from `2026-04-13`
- primary input table: `bars_1m`
- secondary reference table: `raw_ticks`

The first probability indicator should consume `bars_1m` only. `raw_ticks` can be used later to verify bar quality, inspect microstructure around high-probability timestamps, or build separate features, but it should not be required for the initial Kronos probability calculation.

## 6. Strategy Logic Draft

Initial decision policy should be explicit and conservative:

- Long entry when:
  - `mtx_up_50_in_10m_probability >= long_entry_probability`
  - `mtx_down_50_in_10m_probability <= max_opposite_probability`
- Short entry when:
  - `mtx_down_50_in_10m_probability >= short_entry_probability`
  - `mtx_up_50_in_10m_probability <= max_opposite_probability`
- Exit when:
  - current position is long and up probability falls below `long_exit_probability`
  - current position is short and down probability falls below `short_exit_probability`
  - or opposite probability crosses a danger threshold

First version is Kronos-probability standalone. Existing option-power and regime indicators should be shown in reports/UI for manual comparison, but they should not be used as code-level filters until research shows a specific rule is useful.

Suggested initial thresholds for research only:

```text
long_entry_probability: 0.70
short_entry_probability: 0.70
long_exit_probability: 0.45
short_exit_probability: 0.45
max_opposite_probability: 0.35
max_position: 1
execution_mode: next_open
```

Do not hard-code these into the indicator. They belong to strategy config.

## 7. Live Architecture

Live inference should not block tick ingestion or bar aggregation.

Operational interpretation:

- Kronos should normally run once per completed 1m bar.
- Do not run every few seconds against an unfinished K bar in the first version. That would feed unstable OHLCV into a model trained around completed K-line sequences.
- If sub-minute updates are needed later, treat them as preview-only and mark them separately from confirmed bar-close probabilities.

Recommended live flow:

1. Main live service continues ingesting ticks and upserting 1m bars.
2. At each completed 1m bar, enqueue a probability job containing the latest bar window.
3. A single model worker consumes jobs and writes latest probability snapshots into memory and optionally DB/cache.
4. Strategy consumes the latest completed probability snapshot whose timestamp is less than or equal to the decision bar.
5. If inference is late, mark `mtx_probability_ready = 0` and do not trade on stale probability.

Staleness policy:

```text
max_probability_age_seconds: 90
drop_incomplete_lookback: true
trade_when_probability_missing: false
```

Kronos sampling interpretation:

- Kronos tokenizes the recent OHLCV/K-line context into discrete market tokens.
- It autoregressively samples future K-line tokens one step at a time.
- `sample_count` repeats the same context and draws multiple stochastic future paths.
- The probability indicator is computed by counting how many sampled paths hit the configured event, for example `high >= current_close + 50` within the next 10 generated bars.
- This is Monte Carlo-style sampling from the model distribution. It is not a separate market simulator; the randomness comes from token sampling using parameters such as `temperature`, `top_k`, and `top_p`.

## 8. Caching and Persistence

Kronos inference is expensive, so probability rows should be cacheable.

Minimum cache key:

```text
symbol
timeframe
decision_ts
lookback
pred_len
sample_count
probability_targets
model_id
tokenizer_id
temperature
top_k
top_p
context_hash
```

Initial persistence can be file-based JSON under `reports/` or `analysis/`.

Replay UI integration:

```text
PYTHONPATH=src .venv/bin/python -m qt_platform.cli.main \
  --config config/config.yaml \
  serve-option-power-replay \
  --start 2026-04-14T08:45:00 \
  --end 2026-04-14T09:30:00 \
  --kronos-series-json reports/mtx-probability-smoke-10m50.json
```

The replay service loads the Kronos JSON `series` object as external indicator series, adds those names to replay `available_series`, and serves them through the same `/series`, `/bundle`, and `/bundle-by-bars` APIs as option-power indicators. The frontend currently displays the default `10m:50` fields in a `Kronos Probability` panel:

- `mtx_up_50_in_10m_probability`
- `mtx_down_50_in_10m_probability`
- `mtx_expected_close_delta_10m`

Later DB table option:

```text
indicator_snapshots
  ts
  symbol
  indicator_family
  name
  value
  metadata_json
  created_at
```

Avoid storing all raw paths by default. Store raw paths only for sampled audit windows because they can become large.

## 9. Dependency and Packaging Notes

Current `pyproject.toml` does not include Kronos dependencies such as `torch`, `pandas`, `numpy`, `tqdm`, or `huggingface_hub`.

Recommended optional extra:

```text
[project.optional-dependencies]
kronos = [
  "torch",
  "pandas",
  "numpy",
  "tqdm",
  "huggingface_hub",
]
```

Use lazy imports inside `qt_platform.kronos` so normal backtests and option-power workflows do not require ML dependencies.

The pure probability calculator should run without ML dependencies, but it should use a `numpy` fast path when `numpy` is installed or when Kronos returns ndarray paths. Keep the pure Python fallback for lightweight tests and environments without the optional `kronos` extra.

## 10. Validation Plan

Unit tests:

- Raw path mode preserves default averaged Kronos behavior when disabled.
- Probability calculator returns correct up/down probabilities on synthetic paths.
- Bar-to-Kronos feature conversion emits required columns and future timestamps.
- Indicator series maps into `run_backtest()` extras correctly.
- Strategy does not trade when probability is missing, stale, or not ready.

Research validation:

- Run rolling-window probability generation on known MTX windows.
- Compare predicted hit probability buckets against realized hit rate.
- Segment by day/night session.
- Manually compare probability behavior against existing reference fields such as `chop_score`, `pressure_index`, and `raw_pressure`.
- Measure p50/p95/p99 inference latency by model size, `lookback`, `pred_len`, and `sample_count`.

Acceptance gate for live use:

- Probability calibration is directionally meaningful after bucket testing.
- p95 inference latency is below one bar interval or staleness policy prevents trading.
- Strategy result remains stable when `sample_count` is changed within a reasonable range.

## 11. Open Decisions

1. Model choice: start with `Kronos-mini` for speed, or `Kronos-small` for quality.
2. Context window: `256` bars is faster; `512` bars may provide better session context.
3. Sampling count: `32`/`64` for iteration, `100+` only if latency allows.
4. Target set: start with only `10m:50`, but keep the target parser/calculator capable of multiple `minutes:points` pairs.
5. Cache location: JSON file first vs DB table immediately.
6. Which existing reference fields should be added to report overlays first for visual review.

## 12. Recommended Implementation Order

1. Add project-owned Kronos raw-path wrapper with vendored Kronos default behavior unchanged.
2. Add pure probability calculator tests.
3. Add `qt_platform.kronos` adapter and bar conversion helpers with lazy imports.
4. Add offline probability series builder and JSON cache output.
5. Add `mtx-probability` strategy that consumes cached/provided series.
6. Run calibration/backtest research on stored MTX windows.
7. Only after latency is measured, add async live worker integration.

## 13. Implementation Smoke Notes

2026-05-01 local smoke:

- Installed `.venv` optional deps with `pip install -e '.[kronos]'`.
- Added missing Kronos runtime dependencies to the optional extra: `einops` and `safetensors`.
- Environment check:
  - `numpy 2.2.6`
  - `pandas 2.3.3`
  - `torch 2.11.0`
  - MPS available on the local machine
- Real model smoke command succeeded:

```text
PYTHONPATH=src .venv/bin/python -m qt_platform.cli.main \
  --config config/config.yaml \
  build-mtx-probability-series \
  --symbol MTX \
  --start 2026-04-14T08:45:00 \
  --end 2026-04-14T09:30:00 \
  --history-start 2026-04-14T08:00:00 \
  --lookback 32 \
  --target 10m:50 \
  --sample-count 4 \
  --device mps \
  --output reports/mtx-probability-smoke-10m50.json
```

Result:

- `bar_count`: 46
- decision timestamps: 15
- emitted series points: 120
- elapsed wall time: about `11.26s`
- rough throughput: about `0.75s` per decision timestamp with `Kronos-mini`, `pred_len=10`, `sample_count=4`, `lookback=32`, `device=mps`

Initial read:

- This is acceptable for offline indicator generation.
- Live usage should still use a worker/cache model.
- Next performance step is batching multiple decision windows where Kronos supports it, or caching generated series by `(decision_ts, context_hash, model config, target config)`.
