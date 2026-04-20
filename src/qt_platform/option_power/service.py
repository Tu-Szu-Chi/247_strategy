from __future__ import annotations

from collections import deque
import json
import time
import threading
from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from qt_platform.domain import Bar, CanonicalTick, LiveRunMetadata
from qt_platform.features import compute_minute_force_feature_series
from qt_platform.live.recorder import aggregate_ticks_to_bars
from qt_platform.live.shioaji_provider import ShioajiLiveProvider
from qt_platform.option_power.aggregator import OptionPowerAggregator
from qt_platform.session import (
    classify_session,
    is_in_activation_scope,
    is_in_session_scope,
    next_activation_start,
    next_session_start,
)
from qt_platform.storage.base import BarRepository


LIVE_SUBSCRIBE_LEAD_SECONDS = 20.0
OPTION_ROOT_RETRY_SECONDS = 5.0
MAX_LIVE_SNAPSHOTS = 5000
MAX_LIVE_BARS = 720


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
    ) -> None:
        self.provider = provider
        self.store = store
        self.option_root = option_root
        self.expiry_count = expiry_count
        self.atm_window = atm_window
        self.underlying_future_symbol = underlying_future_symbol
        self.call_put = call_put
        self.session_scope = session_scope
        self.batch_size = batch_size
        self.snapshot_interval_seconds = snapshot_interval_seconds
        self.log_callback = log_callback

        self.run_id: str | None = None
        self.reference_price: float | None = None
        self.metadata: LiveRunMetadata | None = None
        self.stop_reason: str | None = None
        self.status = "initialized"
        self.warning: str | None = None
        self.error_message: str | None = None

        self.aggregator = OptionPowerAggregator(option_root=option_root)
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stopped = threading.Event()
        self._history_lock = threading.Lock()
        self._snapshot_history: deque[dict[str, Any]] = deque(maxlen=MAX_LIVE_SNAPSHOTS)
        self._bars_history: deque[dict[str, Any]] = deque(maxlen=MAX_LIVE_BARS)
        self._bar_index: dict[datetime, int] = {}
        self._open_bar_state: _MinuteBarState | None = None
        self._next_snapshot_at: datetime | None = None

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
                return self._snapshot_history[-1]["snapshot"]
        snapshot = self.aggregator.snapshot(
            generated_at=datetime.now(),
            run_id=self.run_id,
            underlying_reference_price=self.reference_price,
            status=self.status,
            stop_reason=self.stop_reason,
            warning=self.warning or self.error_message,
        )
        return snapshot.to_dict()

    def live_metadata(self) -> dict[str, Any]:
        with self._history_lock:
            first_ts = self._snapshot_history[0]["simulated_at"] if self._snapshot_history else None
            last_ts = self._snapshot_history[-1]["simulated_at"] if self._snapshot_history else None
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
                "available_series": [
                    "pressure_index_5m",
                    "pressure_index",
                    "pressure_index_1m",
                    "raw_pressure",
                    "raw_pressure_1m",
                ],
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
        payload: dict[str, list[dict[str, Any]]] = {}
        for name in names:
            payload[name] = [
                {"time": item["simulated_at"], "value": item["snapshot"].get(name, 0)}
                for item in history
            ]
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
            self.reference_price = reference_price
            self._reset_live_cache()
            symbols = [str(getattr(contract, "symbol", "")) for contract in contracts]
            codes = [str(getattr(contract, "code", "")) for contract in contracts]
            underlying_contract = self.provider._resolve_contract(self.underlying_future_symbol)
            all_contracts = [underlying_contract, *contracts]
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
                symbols_json=json.dumps([self.underlying_future_symbol, *symbols], ensure_ascii=False),
                codes_json=json.dumps([underlying_code, *codes], ensure_ascii=False),
                option_root=",".join(selected_roots),
                underlying_future_symbol=self.underlying_future_symbol,
                expiry_count=self.expiry_count,
                atm_window=self.atm_window,
                call_put=self.call_put,
                reference_price=reference_price,
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
                    "expiry_count": self.expiry_count,
                    "atm_window": self.atm_window,
                    "reference_price": reference_price,
                }
            )
            self.status = "running"
            for contract in contracts:
                code = str(getattr(contract, "code", ""))
                self.aggregator.seed_contract(
                    instrument_key=code,
                    symbol=self.option_root,
                    contract_month=str(getattr(contract, "delivery_date", None) or getattr(contract, "delivery_month", "")),
                    strike_price=float(getattr(contract, "strike_price", 0.0)),
                    call_put=_normalize_call_put(getattr(contract, "option_right", None)),
                    session=classify_session(datetime.now()),
                )
            if not self._ready.is_set():
                self._ready.set()
            self._next_snapshot_at = datetime.now()
            for tick in self.provider.stream_ticks_from_contracts(contracts=all_contracts, max_events=None):
                if (tick.instrument_key or tick.symbol) in underlying_identifiers:
                    self.reference_price = tick.price
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
        with self._history_lock:
            self._snapshot_history.clear()
            self._bars_history.clear()
            self._bar_index.clear()
            self._open_bar_state = None
            self._next_snapshot_at = None

    def _ingest_underlying_tick(self, tick: CanonicalTick) -> None:
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

    def _append_closed_bar(self, state: _MinuteBarState) -> None:
        bar = _bar_state_to_chart_dict(state)
        existing_idx = self._bar_index.get(state.minute_ts)
        if existing_idx is not None and existing_idx < len(self._bars_history):
            self._bars_history[existing_idx] = bar
            return
        self._bars_history.append(bar)
        self._bar_index = {datetime.fromisoformat(item["time"]): idx for idx, item in enumerate(self._bars_history)}

    def _maybe_record_snapshots(self, tick_ts: datetime) -> None:
        if self._next_snapshot_at is None:
            self._next_snapshot_at = tick_ts.replace(microsecond=0)
        while self._next_snapshot_at is not None and tick_ts >= self._next_snapshot_at:
            snapshot = self.aggregator.snapshot(
                generated_at=self._next_snapshot_at,
                run_id=self.run_id,
                underlying_reference_price=self.reference_price,
                status=self.status,
                stop_reason=self.stop_reason,
                warning=self.warning or self.error_message,
            ).to_dict()
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


def _canonical_underlying_symbol(value: str) -> str:
    normalized = value.upper()
    if normalized.startswith("MXF"):
        return "MTX"
    if normalized.startswith("TXF"):
        return "MTX"
    return normalized
