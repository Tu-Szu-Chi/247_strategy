from __future__ import annotations

import json
import time
import threading
from dataclasses import replace
from datetime import datetime
from typing import Any

from qt_platform.domain import LiveRunMetadata
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
        snapshot = self.aggregator.snapshot(
            generated_at=datetime.now(),
            run_id=self.run_id,
            underlying_reference_price=self.reference_price,
            status=self.status,
            stop_reason=self.stop_reason,
            warning=self.warning or self.error_message,
        )
        return snapshot.to_dict()

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
            symbols = [str(getattr(contract, "symbol", "")) for contract in contracts]
            codes = [str(getattr(contract, "code", "")) for contract in contracts]
            metadata = LiveRunMetadata(
                run_id=self.run_id or "",
                provider="shioaji",
                mode="option_power_service",
                started_at=datetime.now(),
                session_scope=self.session_scope,
                topic_count=len(contracts),
                symbols_json=json.dumps(symbols, ensure_ascii=False),
                codes_json=json.dumps(codes, ensure_ascii=False),
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
                    "topic_count": len(contracts),
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
            for tick in self.provider.stream_ticks_from_contracts(contracts=contracts, max_events=None):
                self.aggregator.ingest_tick(tick)
                batch.append(tick)
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
