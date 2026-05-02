from __future__ import annotations

from collections import deque
import json
import time
import threading
from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from qt_platform.domain import Bar, CanonicalTick, LiveRunMetadata
from qt_platform.features import compute_minute_force_feature_series
from qt_platform.kronos import ProbabilityTarget, calculate_probability_metrics
from qt_platform.live.recorder import aggregate_ticks_to_bars
from qt_platform.live.shioaji_provider import ShioajiLiveProvider, _contract_month
from qt_platform.option_power.aggregator import OptionPowerAggregator
from qt_platform.option_power.replay import _build_indicator_series
from qt_platform.regime import MtxRegimeAnalyzer, regime_schema_dicts
from qt_platform.session import (
    classify_session,
    is_in_activation_scope,
    is_in_session_scope,
    next_activation_start,
    next_session_start,
    trading_day_for,
)
from qt_platform.storage.base import BarRepository


LIVE_SUBSCRIBE_LEAD_SECONDS = 20.0
OPTION_ROOT_RETRY_SECONDS = 5.0
MAX_LIVE_SNAPSHOTS = 5000
MAX_LIVE_BARS = 720
DAY_INDICATOR_SYMBOL = "TWII"
DAY_INDICATOR_INSTRUMENT_KEY = "index:TWII"
INDEX_REFERENCE_STALE_SECONDS = 30.0


@dataclass
class _MinuteBarState:
    minute_ts: datetime
    trading_day: Any
    symbol: str
    instrument_key: str
    contract_month: str
    strike_price: float | None
    call_put: str | None
    session: str
    source: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    up_ticks: float
    down_ticks: float


@dataclass(frozen=True)
class KronosLiveSettings:
    predictor: Any
    lookback: int
    targets: tuple[ProbabilityTarget, ...]
    sample_count: int
    interval_minutes: int = 1
    temperature: float = 1.0
    top_k: int = 0
    top_p: float = 0.9
    verbose: bool = False
    output_path: str | None = None


class OptionPowerRuntimeService:
    def __init__(
        self,
        *,
        provider: ShioajiLiveProvider,
        store: BarRepository,
        option_root: str,
        expiry_count: int,
        atm_window: int,
        underlying_future_symbol: str,
        call_put: str,
        session_scope: str,
        batch_size: int,
        snapshot_interval_seconds: float,
        log_callback,
        registry_path: str | None = None,
        registry_stock_symbols: list[str] | None = None,
        kronos_live_settings: KronosLiveSettings | None = None,
    ) -> None:
        self.provider = provider
        self.store = store
        self.option_root = option_root
        self.expiry_count = expiry_count
        self.atm_window = atm_window
        self.underlying_future_symbol = underlying_future_symbol
        self.registry_path = registry_path
        self.registry_stock_symbols = sorted(set(registry_stock_symbols or []))
        self.call_put = call_put
        self.session_scope = session_scope
        self.batch_size = batch_size
        self.snapshot_interval_seconds = snapshot_interval_seconds
        self.log_callback = log_callback
        self.kronos_live_settings = kronos_live_settings

        self.run_id: str | None = None
        self.subscription_reference_price: float | None = None
        self.underlying_reference_price: float | None = None
        self.underlying_reference_source: str | None = None
        self._underlying_future_price: float | None = None
        self._underlying_future_tick_ts: datetime | None = None
        self._day_indicator_contract = None
        self._day_indicator_price: float | None = None
        self._day_indicator_tick_ts: datetime | None = None
        self.metadata: LiveRunMetadata | None = None
        self.stop_reason: str | None = None
        self.status = "initialized"
        self.warning: str | None = None
        self.error_message: str | None = None

        self.aggregator = OptionPowerAggregator(option_root=option_root)
        self.regime = MtxRegimeAnalyzer()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stopped = threading.Event()
        self._history_lock = threading.Lock()
        self._snapshot_history: deque[dict[str, Any]] = deque(maxlen=MAX_LIVE_SNAPSHOTS)
        self._bars_history: deque[dict[str, Any]] = deque(maxlen=MAX_LIVE_BARS)
        self._bar_index: dict[datetime, int] = {}
        self._open_bar_state: _MinuteBarState | None = None
        self._day_indicator_bar_state: _MinuteBarState | None = None
        self._next_snapshot_at: datetime | None = None
        self._underlying_domain_bars: deque[Bar] = deque(maxlen=MAX_LIVE_BARS)
        self._kronos_thread: threading.Thread | None = None
        self._kronos_last_decision_time: datetime | None = None
        self._kronos_last_completed_at: datetime | None = None
        self._kronos_last_duration_seconds: float | None = None
        self._kronos_status = "disabled" if kronos_live_settings is None else "idle"
        self._kronos_error: str | None = None
        self._kronos_busy_skip_count = 0
        self._kronos_series_history: dict[str, list[dict[str, Any]]] = {}
        self._kronos_latest_metrics: dict[str, float | int] = {}

    def start(self, run_id: str) -> None:
        if self._thread and self._thread.is_alive():
            raise RuntimeError("OptionPowerRuntimeService is already running.")
        self.run_id = run_id
        self._thread = threading.Thread(target=self._run, name="option-power-runtime", daemon=True)
        self._thread.start()

    def wait_until_ready(self, timeout: float) -> bool:
        return self._ready.wait(timeout=timeout)

    def join(self, timeout: float | None = None) -> None:
        if self._thread is None:
            return
        self._thread.join(timeout=timeout)

    def current_snapshot(self) -> dict[str, Any]:
        with self._history_lock:
            if self._snapshot_history:
                snapshot = dict(self._snapshot_history[-1]["snapshot"])
                snapshot["kronos"] = self._kronos_snapshot_payload()
                snapshot.update(self._kronos_latest_metrics)
                return snapshot
        snapshot = self.aggregator.snapshot(
            generated_at=datetime.now(),
            run_id=self.run_id,
            underlying_reference_price=self.underlying_reference_price,
            underlying_reference_source=self.underlying_reference_source,
            status=self.status,
            regime=self.regime.snapshot(datetime.now()),
            stop_reason=self.stop_reason,
            warning=self.warning or self.error_message,
        )
        payload = snapshot.to_dict()
        payload["kronos"] = self._kronos_snapshot_payload()
        payload.update(self._kronos_latest_metrics)
        return payload

    def live_latest_update(
        self,
        *,
        since: datetime | None = None,
        names: list[str] | None = None,
        include_bar: bool = True,
    ) -> dict[str, Any]:
        with self._history_lock:
            latest_entry = self._snapshot_history[-1] if self._snapshot_history else None
            latest_bar = None
            if include_bar:
                latest_bar = _bar_state_to_chart_dict(self._open_bar_state)
                if latest_bar is None and self._bars_history:
                    latest_bar = self._bars_history[-1]

        snapshot_time = latest_entry["simulated_at"] if latest_entry is not None else None
        updated = False
        if snapshot_time is not None:
            updated = since is None or datetime.fromisoformat(snapshot_time) > since

        payload: dict[str, Any] = {
            "updated": updated,
            "snapshot_time": snapshot_time,
            "snapshot": None,
            "contract_totals": None,
            "series": {},
            "latest_bar": latest_bar,
        }
        if not updated or latest_entry is None:
            return payload

        snapshot = latest_entry["snapshot"]
        payload["snapshot"] = _compact_snapshot(snapshot)
        payload["contract_totals"] = _snapshot_contract_totals(snapshot)
        if names:
            indicator_series = _build_indicator_series([snapshot_time], [snapshot])
            payload["series"] = {
                name: indicator_series.get(name, [])[-1:]
                for name in names
            }
            with self._history_lock:
                for name in names:
                    if name in self._kronos_series_history:
                        payload["series"][name] = self._kronos_series_history[name][-1:]
        return payload

    def live_metadata(self) -> dict[str, Any]:
        with self._history_lock:
            first_ts = self._snapshot_history[0]["simulated_at"] if self._snapshot_history else None
            last_ts = self._snapshot_history[-1]["simulated_at"] if self._snapshot_history else None
        available_series = sorted(self.live_series(["__all__"]).keys())
        return {
            "mode": "live",
            "run_id": self.run_id,
            "status": self.status,
            "option_root": self.aggregator.option_root,
            "underlying_symbol": _canonical_underlying_symbol(self.underlying_future_symbol),
            "snapshot_count": len(self._snapshot_history),
            "bar_count": len(self._bars_history),
            "start": first_ts,
            "end": last_ts,
            "selected_option_roots": [
                item for item in self.aggregator.option_root.split(",") if item
            ],
            "available_series": available_series,
            "regime_schema": regime_schema_dicts(),
            "kronos": self._kronos_snapshot_payload(),
        }

    def live_bars(self) -> list[dict[str, Any]]:
        with self._history_lock:
            bars = list(self._bars_history)
            open_bar = _bar_state_to_chart_dict(self._open_bar_state) if self._open_bar_state else None
        if open_bar:
            if bars and bars[-1]["time"] == open_bar["time"]:
                bars[-1] = open_bar
            else:
                bars.append(open_bar)
        return bars

    def live_series(self, names: list[str]) -> dict[str, list[dict[str, Any]]]:
        with self._history_lock:
            history = list(self._snapshot_history)
        snapshot_times = [item["simulated_at"] for item in history]
        snapshots = [item["snapshot"] for item in history]
        full_series = _build_indicator_series(snapshot_times, snapshots)
        with self._history_lock:
            for name, points in self._kronos_series_history.items():
                full_series[name] = list(points)
        if names == ["__all__"]:
            return full_series
        payload: dict[str, list[dict[str, Any]]] = {}
        for name in names:
            payload[name] = full_series.get(name, [])
        return payload

    def live_snapshot_at(self, ts: datetime) -> dict[str, Any] | None:
        with self._history_lock:
            history = list(self._snapshot_history)
        if not history:
            return None
        target = ts.isoformat()
        best = min(
            history,
            key=lambda item: abs(datetime.fromisoformat(item["simulated_at"]) - datetime.fromisoformat(target)),
        )
        return best

    def _run(self) -> None:
        ready_emitted = False
        try:
            while True:
                now = datetime.now()
                if not is_in_activation_scope(now, self.session_scope, lead_seconds=LIVE_SUBSCRIBE_LEAD_SECONDS):
                    wake_at = next_activation_start(now, self.session_scope, lead_seconds=LIVE_SUBSCRIBE_LEAD_SECONDS)
                    session_wake_at = next_session_start(now, self.session_scope)
                    self.status = "waiting_for_session"
                    self.stop_reason = None
                    self.log_callback(
                        {
                            "status": "waiting_for_session",
                            "run_id": self.run_id,
                            "now": now.isoformat(),
                            "wake_at": wake_at.isoformat(),
                            "session_wake_at": session_wake_at.isoformat(),
                            "subscribe_lead_seconds": LIVE_SUBSCRIBE_LEAD_SECONDS,
                            "session_scope": self.session_scope,
                        }
                    )
                    if not ready_emitted:
                        self._ready.set()
                        ready_emitted = True
                    _sleep_until(wake_at)
                    continue

                self._run_cycle()
                if not ready_emitted:
                    self._ready.set()
                    ready_emitted = True

                if self.stop_reason == "session_closed":
                    continue
                if self.status == "waiting_for_option_roots":
                    continue
                if self.stop_reason == "usage_threshold_reached":
                    self.status = "paused_for_usage_limit"
                    self.log_callback(
                        {
                            "status": "paused_for_usage_limit",
                            "run_id": self.run_id,
                        }
                    )
                    return
                if self.status == "completed":
                    return
                time.sleep(1.0)
        except Exception as exc:
            self.error_message = str(exc)
            self.status = "error"
            if self.metadata:
                self.store.create_live_run(replace(self.metadata, status="error"))
            if not ready_emitted:
                self._ready.set()
            raise
        finally:
            self._stopped.set()

    def _run_cycle(self) -> None:
        batch: list = []
        try:
            self.warning = None
            self.status = "connecting"
            self.provider.connect()
            self.log_callback(
                {
                    "status": "connected",
                    "provider": "shioaji",
                    "run_id": self.run_id,
                }
            )
            self.status = "resolving_universe"
            try:
                selected_roots, contracts, reference_price = self.provider.resolve_option_universe(
                    option_root=self.option_root,
                    expiry_count=self.expiry_count,
                    atm_window=self.atm_window,
                    underlying_future_symbol=self.underlying_future_symbol,
                    call_put=self.call_put,
                )
            except ValueError as exc:
                if "No option contracts found for roots" not in str(exc):
                    raise
                diagnostics = self.provider.option_root_diagnostics(now=datetime.now())
                self.warning = str(exc)
                self.status = "waiting_for_option_roots"
                self.stop_reason = None
                self.log_callback(
                    {
                        "status": "waiting_for_option_roots",
                        "run_id": self.run_id,
                        "message": str(exc),
                        "retry_in_seconds": OPTION_ROOT_RETRY_SECONDS,
                        "available_option_roots": diagnostics["available_roots"],
                        "root_diagnostics": diagnostics["roots"],
                    }
                )
                time.sleep(OPTION_ROOT_RETRY_SECONDS)
                return
            for contract in contracts:
                code = str(getattr(contract, "code", "") or "")
                target_code = str(getattr(contract, "target_code", "") or "")
                if code:
                    self.provider._contracts[code] = contract
                if target_code:
                    self.provider._contracts[target_code] = contract
            self.aggregator.set_option_root(",".join(selected_roots))
            self.subscription_reference_price = reference_price
            self._underlying_future_price = reference_price
            self._underlying_future_tick_ts = datetime.now()
            self._day_indicator_contract = None
            self._day_indicator_price = None
            self._day_indicator_tick_ts = None
            self._refresh_indicator_reference(datetime.now())
            self._reset_live_cache()
            symbols = [str(getattr(contract, "symbol", "")) for contract in contracts]
            codes = [str(getattr(contract, "code", "")) for contract in contracts]
            underlying_contract = self.provider._resolve_contract(self.underlying_future_symbol)
            registry_contracts = [
                self.provider._resolve_contract(symbol)
                for symbol in self.registry_stock_symbols
            ]
            indicator_contract = None
            try:
                indicator_contract = self.provider.resolve_taiex_contract()
                self._day_indicator_contract = indicator_contract
                self._refresh_day_indicator_snapshot(datetime.now())
            except Exception as exc:
                self.warning = str(exc)
            stock_symbols = [str(getattr(contract, "symbol", "")) for contract in registry_contracts]
            stock_codes = [str(getattr(contract, "code", "")) for contract in registry_contracts]
            all_contracts = [underlying_contract, *registry_contracts, *contracts]
            unique_all_contracts = {}
            for contract in all_contracts:
                key = str(getattr(contract, "code", None) or getattr(contract, "symbol", None))
                unique_all_contracts[key] = contract
            all_contracts = list(unique_all_contracts.values())
            underlying_code = str(getattr(underlying_contract, "code", "") or self.underlying_future_symbol)
            underlying_target_code = str(getattr(underlying_contract, "target_code", "") or "")
            underlying_identifiers = {
                value
                for value in {
                    self.underlying_future_symbol,
                    underlying_code,
                    underlying_target_code,
                }
                if value
            }
            if underlying_code:
                self.provider._contracts[underlying_code] = underlying_contract
            if underlying_target_code:
                self.provider._contracts[underlying_target_code] = underlying_contract
            metadata = LiveRunMetadata(
                run_id=self.run_id or "",
                provider="shioaji",
                mode="option_power_service",
                started_at=datetime.now(),
                session_scope=self.session_scope,
                topic_count=len(all_contracts),
                symbols_json=json.dumps(
                    [self.underlying_future_symbol, *stock_symbols, *symbols],
                    ensure_ascii=False,
                ),
                codes_json=json.dumps(
                    [underlying_code, *stock_codes, *codes],
                    ensure_ascii=False,
                ),
                option_root=",".join(selected_roots),
                underlying_future_symbol=self.underlying_future_symbol,
                expiry_count=self.expiry_count,
                atm_window=self.atm_window,
                call_put=self.call_put,
                reference_price=self.subscription_reference_price,
                status="started",
            )
            self.store.create_live_run(metadata)
            self.metadata = metadata
            self.log_callback(
                {
                    "status": "subscribed",
                    "run_id": self.run_id,
                    "topic_count": len(all_contracts),
                    "option_roots": selected_roots,
                    "registry_path": self.registry_path,
                    "registry_stock_count": len(self.registry_stock_symbols),
                    "registry_stock_symbols": self.registry_stock_symbols,
                    "expiry_count": self.expiry_count,
                    "atm_window": self.atm_window,
                    "reference_price": self.subscription_reference_price,
                    "indicator_symbol": DAY_INDICATOR_SYMBOL if indicator_contract is not None else None,
                }
            )
            self.status = "running"
            for contract in contracts:
                code = str(getattr(contract, "code", ""))
                self.aggregator.seed_contract(
                    instrument_key=code,
                    symbol=self.option_root,
                    contract_month=_contract_month(contract),
                    strike_price=float(getattr(contract, "strike_price", 0.0)),
                    call_put=_normalize_call_put(getattr(contract, "option_right", None)),
                    session=classify_session(datetime.now()),
                )
            if not self._ready.is_set():
                self._ready.set()
            self._next_snapshot_at = datetime.now()
            for tick in self.provider.stream_ticks_from_contracts(contracts=all_contracts, max_events=None):
                if (tick.instrument_key or tick.symbol) in underlying_identifiers:
                    self._underlying_future_price = tick.price
                    self._underlying_future_tick_ts = tick.ts
                    self.subscription_reference_price = tick.price
                    self._refresh_indicator_reference(tick.ts)
                    self._ingest_underlying_tick(tick)
                else:
                    self.aggregator.ingest_tick(tick)
                batch.append(tick)
                self._maybe_record_snapshots(tick.ts)
                if len(batch) >= self.batch_size:
                    self._flush_batch(batch)
                    batch = []
            if batch:
                self._flush_batch(batch)
            self.stop_reason = self.provider.stop_reason()
            self.status = self.stop_reason or "completed"
            if self.metadata:
                self.store.create_live_run(replace(self.metadata, status=self.status))
        finally:
            if batch:
                self._flush_batch(batch)
            self.provider.close()

    def _flush_batch(self, ticks: list) -> None:
        if not ticks:
            return
        self.store.append_ticks(ticks)
        bars = aggregate_ticks_to_bars(ticks)
        self.store.upsert_bars("1m", bars)
        self.store.upsert_minute_force_features(
            compute_minute_force_feature_series(bars, run_id=self.run_id)
        )

    def _reset_live_cache(self) -> None:
        self.regime = MtxRegimeAnalyzer()
        with self._history_lock:
            self._snapshot_history.clear()
            self._bars_history.clear()
            self._bar_index.clear()
            self._open_bar_state = None
            self._day_indicator_bar_state = None
            self._next_snapshot_at = None
            self._underlying_domain_bars.clear()
            self._kronos_thread = None
            self._kronos_last_decision_time = None
            self._kronos_last_completed_at = None
            self._kronos_last_duration_seconds = None
            self._kronos_status = "disabled" if self.kronos_live_settings is None else "idle"
            self._kronos_error = None
            self._kronos_busy_skip_count = 0
            self._kronos_series_history = {}
            self._kronos_latest_metrics = {}

    def _ingest_underlying_tick(self, tick: CanonicalTick) -> None:
        self.regime.ingest_tick(tick)
        minute_ts = tick.ts.replace(second=0, microsecond=0)
        with self._history_lock:
            if self._open_bar_state is None or self._open_bar_state.minute_ts != minute_ts:
                if self._open_bar_state is not None:
                    self._append_closed_bar(self._open_bar_state)
                self._open_bar_state = _MinuteBarState(
                    minute_ts=minute_ts,
                    trading_day=tick.trading_day,
                    symbol=tick.symbol,
                    instrument_key=tick.instrument_key or tick.symbol,
                    contract_month=tick.contract_month,
                    strike_price=tick.strike_price,
                    call_put=tick.call_put,
                    session=tick.session,
                    source=tick.source,
                    open=tick.price,
                    high=tick.price,
                    low=tick.price,
                    close=tick.price,
                    volume=tick.size,
                    up_ticks=1.0 if tick.tick_direction == "up" else 0.0,
                    down_ticks=1.0 if tick.tick_direction == "down" else 0.0,
                )
                self.regime.ingest_bar(_bar_state_to_domain_bar(self._open_bar_state))
                return

            state = self._open_bar_state
            state.high = max(state.high, tick.price)
            state.low = min(state.low, tick.price)
            state.close = tick.price
            state.volume += tick.size
            if tick.tick_direction == "up":
                state.up_ticks += 1
            elif tick.tick_direction == "down":
                state.down_ticks += 1
            self.regime.ingest_bar(_bar_state_to_domain_bar(state))

    def _append_closed_bar(self, state: _MinuteBarState) -> None:
        bar = _bar_state_to_chart_dict(state)
        domain_bar = _bar_state_to_domain_bar(state)
        existing_idx = self._bar_index.get(state.minute_ts)
        if existing_idx is not None and existing_idx < len(self._bars_history):
            self._bars_history[existing_idx] = bar
            if self._underlying_domain_bars:
                self._underlying_domain_bars[-1] = domain_bar
            self._maybe_start_kronos_inference(state.minute_ts)
            return
        self._bars_history.append(bar)
        self._underlying_domain_bars.append(domain_bar)
        self._bar_index = {datetime.fromisoformat(item["time"]): idx for idx, item in enumerate(self._bars_history)}
        self._maybe_start_kronos_inference(state.minute_ts)

    def _upsert_day_indicator_bar(self, state: _MinuteBarState) -> None:
        self.store.upsert_bars(
            "1m",
            [
                Bar(
                    ts=state.minute_ts,
                    trading_day=state.trading_day,
                    symbol=state.symbol,
                    instrument_key=state.instrument_key,
                    contract_month=state.contract_month,
                    strike_price=state.strike_price,
                    call_put=state.call_put,
                    session=state.session,
                    open=state.open,
                    high=state.high,
                    low=state.low,
                    close=state.close,
                    volume=state.volume,
                    open_interest=None,
                    source=state.source,
                    up_ticks=state.up_ticks,
                    down_ticks=state.down_ticks,
                    build_source="live_snapshot_agg",
                )
            ],
        )

    def _maybe_record_snapshots(self, tick_ts: datetime) -> None:
        if self._next_snapshot_at is None:
            self._next_snapshot_at = tick_ts.replace(microsecond=0)
        while self._next_snapshot_at is not None and tick_ts >= self._next_snapshot_at:
            self._refresh_day_indicator_snapshot(self._next_snapshot_at)
            self._refresh_indicator_reference(self._next_snapshot_at)
            snapshot = self.aggregator.snapshot(
                generated_at=self._next_snapshot_at,
                run_id=self.run_id,
                underlying_reference_price=self.underlying_reference_price,
                underlying_reference_source=self.underlying_reference_source,
                status=self.status,
                regime=self.regime.snapshot(self._next_snapshot_at),
                stop_reason=self.stop_reason,
                warning=self.warning or self.error_message,
            ).to_dict()
            snapshot["kronos"] = self._kronos_snapshot_payload()
            snapshot.update(self._kronos_latest_metrics)
            with self._history_lock:
                self._snapshot_history.append(
                    {
                        "session_id": self.run_id,
                        "index": len(self._snapshot_history),
                        "simulated_at": self._next_snapshot_at.isoformat(),
                        "snapshot": snapshot,
                    }
                )
            self._next_snapshot_at += timedelta(seconds=self.snapshot_interval_seconds)

    def _maybe_start_kronos_inference(self, decision_bar_time: datetime) -> None:
        settings = self.kronos_live_settings
        if settings is None:
            return
        if len(self._underlying_domain_bars) < settings.lookback:
            self._kronos_status = "waiting_for_lookback"
            return
        if self._kronos_last_decision_time is not None and decision_bar_time <= self._kronos_last_decision_time:
            return
        if self._kronos_thread is not None and self._kronos_thread.is_alive():
            self._kronos_busy_skip_count += 1
            self._kronos_status = "lagging"
            self.log_callback(
                {
                    "status": "kronos_live_lagging",
                    "run_id": self.run_id,
                    "decision_bar_time": decision_bar_time.isoformat(),
                    "busy_skip_count": self._kronos_busy_skip_count,
                }
            )
            return
        bars = list(self._underlying_domain_bars)[-settings.lookback:]
        self._kronos_status = "running"
        self._kronos_error = None
        self._kronos_last_decision_time = decision_bar_time
        self._kronos_thread = threading.Thread(
            target=self._run_kronos_inference,
            args=(decision_bar_time, bars),
            name="option-power-kronos-live",
            daemon=True,
        )
        self._kronos_thread.start()

    def _run_kronos_inference(self, decision_bar_time: datetime, bars: list[Bar]) -> None:
        settings = self.kronos_live_settings
        if settings is None:
            return
        started = time.perf_counter()
        try:
            pred_len = max(target.horizon_steps(bar_minutes=1.0) for target in settings.targets)
            paths = settings.predictor.predict_paths(
                bars,
                pred_len=pred_len,
                sample_count=settings.sample_count,
                temperature=settings.temperature,
                top_k=settings.top_k,
                top_p=settings.top_p,
                verbose=settings.verbose,
            )
            metrics = calculate_probability_metrics(
                paths,
                current_close=bars[-1].close,
                targets=settings.targets,
                bar_minutes=1.0,
                include_status_metrics=False,
                include_sample_count=False,
                include_path_delta_percentiles=False,
            )
            duration = time.perf_counter() - started
            with self._history_lock:
                for name, value in metrics.items():
                    point = {"time": decision_bar_time.isoformat(), "value": value}
                    series = self._kronos_series_history.setdefault(name, [])
                    if series and series[-1]["time"] == point["time"]:
                        series[-1] = point
                    else:
                        series.append(point)
                self._kronos_latest_metrics = dict(metrics)
                self._kronos_last_completed_at = datetime.now()
                self._kronos_last_duration_seconds = duration
                self._kronos_status = "ready"
                self._kronos_error = None
                completed_at = self._kronos_last_completed_at
                self._append_kronos_snapshot_locked(completed_at)
                self._persist_kronos_series_locked(settings.output_path, decision_bar_time, completed_at)
            self.log_callback(
                {
                    "status": "kronos_live_ready",
                    "run_id": self.run_id,
                    "decision_bar_time": decision_bar_time.isoformat(),
                    "duration_seconds": round(duration, 4),
                    "series_names": sorted(metrics.keys()),
                }
            )
        except Exception as exc:
            duration = time.perf_counter() - started
            self._kronos_last_duration_seconds = duration
            self._kronos_status = "error"
            self._kronos_error = str(exc)
            self.log_callback(
                {
                    "status": "kronos_live_error",
                    "run_id": self.run_id,
                    "decision_bar_time": decision_bar_time.isoformat(),
                    "duration_seconds": round(duration, 4),
                    "message": str(exc),
                }
            )

    def _kronos_snapshot_payload(self) -> dict[str, Any]:
        return {
            "status": self._kronos_status,
            "last_decision_time": self._kronos_last_decision_time.isoformat() if self._kronos_last_decision_time is not None else None,
            "last_completed_at": self._kronos_last_completed_at.isoformat() if self._kronos_last_completed_at is not None else None,
            "last_duration_seconds": self._kronos_last_duration_seconds,
            "error": self._kronos_error,
            "busy_skip_count": self._kronos_busy_skip_count,
            "available_series": sorted(self._kronos_series_history.keys()),
        }

    def _append_kronos_snapshot_locked(self, completed_at: datetime) -> None:
        if self._snapshot_history:
            snapshot = dict(self._snapshot_history[-1]["snapshot"])
        else:
            snapshot = self.aggregator.snapshot(
                generated_at=completed_at,
                run_id=self.run_id,
                underlying_reference_price=self.underlying_reference_price,
                underlying_reference_source=self.underlying_reference_source,
                status=self.status,
                regime=self.regime.snapshot(completed_at),
                stop_reason=self.stop_reason,
                warning=self.warning or self.error_message,
            ).to_dict()
        snapshot["generated_at"] = completed_at.isoformat()
        snapshot["kronos"] = self._kronos_snapshot_payload()
        snapshot.update(self._kronos_latest_metrics)
        self._snapshot_history.append(
            {
                "session_id": self.run_id,
                "index": len(self._snapshot_history),
                "simulated_at": completed_at.isoformat(),
                "snapshot": snapshot,
            }
        )

    def _persist_kronos_series_locked(
        self,
        output_path: str | None,
        decision_bar_time: datetime,
        completed_at: datetime,
    ) -> None:
        if not output_path:
            return
        payload = {
            "metadata": {
                "mode": "live",
                "run_id": self.run_id,
                "generated_at": completed_at.isoformat(),
                "decision_time": self._kronos_last_decision_time.isoformat() if self._kronos_last_decision_time is not None else None,
                "available_series": sorted(self._kronos_series_history.keys()),
            },
            "series": self._kronos_series_history,
        }
        path = _resolve_kronos_daily_output_path(output_path, decision_bar_time)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _refresh_day_indicator_snapshot(self, now: datetime) -> None:
        if self._day_indicator_contract is None or classify_session(now) != "day":
            return
        try:
            self._day_indicator_price = self.provider.snapshot_price(self._day_indicator_contract)
            self._day_indicator_tick_ts = now
            self._ingest_day_indicator_price(now, self._day_indicator_price)
        except Exception:
            pass

    def _ingest_day_indicator_price(self, now: datetime, price: float) -> None:
        minute_ts = now.replace(second=0, microsecond=0)
        if self._day_indicator_bar_state is None or self._day_indicator_bar_state.minute_ts != minute_ts:
            if self._day_indicator_bar_state is not None:
                self._upsert_day_indicator_bar(self._day_indicator_bar_state)
            self._day_indicator_bar_state = _MinuteBarState(
                minute_ts=minute_ts,
                trading_day=trading_day_for(now),
                symbol=DAY_INDICATOR_SYMBOL,
                instrument_key=DAY_INDICATOR_INSTRUMENT_KEY,
                contract_month="",
                strike_price=None,
                call_put=None,
                session="day",
                source="shioaji_snapshot",
                open=price,
                high=price,
                low=price,
                close=price,
                volume=0.0,
                up_ticks=0.0,
                down_ticks=0.0,
            )
            self._upsert_day_indicator_bar(self._day_indicator_bar_state)
            return

        state = self._day_indicator_bar_state
        state.high = max(state.high, price)
        state.low = min(state.low, price)
        state.close = price
        self._upsert_day_indicator_bar(state)

    def _refresh_indicator_reference(self, now: datetime) -> None:
        current_session = classify_session(now)
        if current_session == "day":
            if (
                self._day_indicator_price is not None
                and self._day_indicator_tick_ts is not None
                and (now - self._day_indicator_tick_ts).total_seconds() <= INDEX_REFERENCE_STALE_SECONDS
            ):
                self.underlying_reference_price = self._day_indicator_price
                self.underlying_reference_source = DAY_INDICATOR_SYMBOL.lower()
                return
        self.underlying_reference_price = self._underlying_future_price
        self.underlying_reference_source = self.underlying_future_symbol.lower() if self._underlying_future_price is not None else None


def _normalize_call_put(option_right) -> str:
    raw = getattr(option_right, "value", option_right)
    normalized = str(raw).strip().lower()
    if normalized in {"c", "call", "buy"}:
        return "call"
    if normalized in {"p", "put", "sell"}:
        return "put"
    return normalized or "unknown"


def _sleep_until(target: datetime) -> None:
    while True:
        now = datetime.now()
        remaining = (target - now).total_seconds()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 30.0))


def _bar_state_to_chart_dict(state: _MinuteBarState | None) -> dict[str, Any] | None:
    if state is None:
        return None
    return {
        "time": state.minute_ts.isoformat(),
        "open": state.open,
        "high": state.high,
        "low": state.low,
        "close": state.close,
        "volume": state.volume,
    }


def _bar_state_to_domain_bar(state: _MinuteBarState) -> Bar:
    return Bar(
        ts=state.minute_ts,
        trading_day=state.trading_day,
        symbol=state.symbol,
        instrument_key=state.instrument_key,
        contract_month=state.contract_month,
        strike_price=state.strike_price,
        call_put=state.call_put,
        session=state.session,
        open=state.open,
        high=state.high,
        low=state.low,
        close=state.close,
        volume=state.volume,
        open_interest=None,
        source=state.source,
        up_ticks=state.up_ticks,
        down_ticks=state.down_ticks,
        build_source="live_snapshot_agg",
    )


def _resolve_kronos_daily_output_path(output_path: str, decision_bar_time: datetime) -> Path:
    base_path = Path(output_path)
    date_token = decision_bar_time.date().isoformat()
    if base_path.suffix.lower() == ".json":
        stem = base_path.stem
        filename = f"{stem}-{date_token}.json"
        return base_path.with_name(filename)
    return base_path / f"kronos-live-{date_token}.json"


def _canonical_underlying_symbol(value: str) -> str:
    normalized = value.upper()
    if normalized.startswith("MXF"):
        return "MTX"
    if normalized.startswith("TXF"):
        return "MTX"
    return normalized


def _compact_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": snapshot.get("type"),
        "generated_at": snapshot.get("generated_at"),
        "run_id": snapshot.get("run_id"),
        "session": snapshot.get("session"),
        "option_root": snapshot.get("option_root"),
        "underlying_reference_price": snapshot.get("underlying_reference_price"),
        "underlying_reference_source": snapshot.get("underlying_reference_source"),
        "raw_pressure": snapshot.get("raw_pressure"),
        "pressure_index": snapshot.get("pressure_index"),
        "raw_pressure_weighted": snapshot.get("raw_pressure_weighted"),
        "pressure_index_weighted": snapshot.get("pressure_index_weighted"),
        "regime": snapshot.get("regime"),
        "iv_surface": snapshot.get("iv_surface"),
        "contract_count": snapshot.get("contract_count"),
        "status": snapshot.get("status"),
        "stop_reason": snapshot.get("stop_reason"),
        "warning": snapshot.get("warning"),
        "kronos": snapshot.get("kronos"),
        "mtx_up_50_in_10m_probability": snapshot.get("mtx_up_50_in_10m_probability"),
        "mtx_down_50_in_10m_probability": snapshot.get("mtx_down_50_in_10m_probability"),
        "mtx_expected_close_delta_10m": snapshot.get("mtx_expected_close_delta_10m"),
    }


def _snapshot_contract_totals(snapshot: dict[str, Any]) -> dict[str, dict[str, float]]:
    totals = {
        "call": {"cumulative_power": 0.0, "power_1m_delta": 0.0},
        "put": {"cumulative_power": 0.0, "power_1m_delta": 0.0},
    }
    for expiry in snapshot.get("expiries") or []:
        for contract in expiry.get("contracts") or []:
            side = contract.get("call_put")
            if side not in totals:
                continue
            totals[side]["cumulative_power"] += float(contract.get("cumulative_power") or 0.0)
            totals[side]["power_1m_delta"] += float(contract.get("power_1m_delta") or 0.0)
    return totals
