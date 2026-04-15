from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import Lock

from qt_platform.domain import CanonicalTick
from qt_platform.option_power.domain import (
    OptionContractSnapshot,
    OptionExpirySnapshot,
    OptionPowerSnapshot,
)


@dataclass
class _VolumeEvent:
    ts: datetime
    buy_volume: float
    sell_volume: float
    unknown_volume: float


@dataclass
class _ContractState:
    instrument_key: str
    symbol: str
    contract_month: str
    strike_price: float
    call_put: str
    last_price: float | None = None
    cumulative_buy_volume: float = 0.0
    cumulative_sell_volume: float = 0.0
    unknown_volume: float = 0.0
    last_tick_ts: datetime | None = None
    events: deque[_VolumeEvent] = field(default_factory=deque)


class OptionPowerAggregator:
    def __init__(
        self,
        option_root: str,
        rolling_window_seconds: int = 60,
    ) -> None:
        self.option_root = option_root
        self.rolling_window = timedelta(seconds=rolling_window_seconds)
        self._lock = Lock()
        self._session = "unknown"
        self._states: dict[str, _ContractState] = {}

    def ingest_tick(self, tick: CanonicalTick) -> None:
        if tick.strike_price is None or tick.call_put is None:
            return
        if tick.session not in {"day", "night"}:
            return

        buy_volume = 0.0
        sell_volume = 0.0
        unknown_volume = 0.0
        if tick.tick_direction == "up":
            buy_volume = float(tick.size)
        elif tick.tick_direction == "down":
            sell_volume = float(tick.size)
        else:
            unknown_volume = float(tick.size)

        with self._lock:
            if self._session != tick.session:
                self._session = tick.session
                self._states = {}

            state = self._states.get(tick.instrument_key or "")
            if state is None:
                state = _ContractState(
                    instrument_key=tick.instrument_key or "",
                    symbol=tick.symbol,
                    contract_month=tick.contract_month,
                    strike_price=float(tick.strike_price),
                    call_put=tick.call_put,
                )
                self._states[state.instrument_key] = state

            state.cumulative_buy_volume += buy_volume
            state.cumulative_sell_volume += sell_volume
            state.unknown_volume += unknown_volume
            state.last_tick_ts = tick.ts
            state.last_price = tick.price
            state.events.append(
                _VolumeEvent(
                    ts=tick.ts,
                    buy_volume=buy_volume,
                    sell_volume=sell_volume,
                    unknown_volume=unknown_volume,
                )
            )
            self._evict_expired_events(state, tick.ts)

    def seed_contract(
        self,
        *,
        instrument_key: str,
        symbol: str,
        contract_month: str,
        strike_price: float,
        call_put: str,
        session: str,
    ) -> None:
        if session not in {"day", "night"}:
            return
        with self._lock:
            if self._session != session:
                self._session = session
                self._states = {}
            self._states.setdefault(
                instrument_key,
                _ContractState(
                    instrument_key=instrument_key,
                    symbol=symbol,
                    contract_month=contract_month,
                    strike_price=strike_price,
                    call_put=call_put,
                ),
            )

    def snapshot(
        self,
        generated_at: datetime,
        run_id: str | None,
        underlying_reference_price: float | None,
        status: str,
        stop_reason: str | None = None,
        warning: str | None = None,
    ) -> OptionPowerSnapshot:
        with self._lock:
            expiries: dict[str, list[OptionContractSnapshot]] = {}
            contract_count = 0
            for state in self._states.values():
                rolling_buy, rolling_sell = self._rolling_totals(state, generated_at)
                contract = OptionContractSnapshot(
                    instrument_key=state.instrument_key,
                    symbol=state.symbol,
                    contract_month=state.contract_month,
                    strike_price=state.strike_price,
                    call_put=state.call_put,
                    last_price=state.last_price,
                    cumulative_buy_volume=state.cumulative_buy_volume,
                    cumulative_sell_volume=state.cumulative_sell_volume,
                    cumulative_power=state.cumulative_buy_volume - state.cumulative_sell_volume,
                    rolling_1m_buy_volume=rolling_buy,
                    rolling_1m_sell_volume=rolling_sell,
                    power_1m_delta=rolling_buy - rolling_sell,
                    unknown_volume=state.unknown_volume,
                    last_tick_ts=state.last_tick_ts.isoformat() if state.last_tick_ts else None,
                )
                expiries.setdefault(state.contract_month, []).append(contract)
                contract_count += 1

            expiry_snapshots = [
                OptionExpirySnapshot(
                    contract_month=contract_month,
                    label=contract_month,
                    contracts=sorted(
                        contracts,
                        key=lambda item: (
                            item.strike_price,
                            0 if item.call_put == "call" else 1,
                            item.instrument_key,
                        ),
                    ),
                )
                for contract_month, contracts in sorted(expiries.items())
            ]

            return OptionPowerSnapshot(
                type="option_power_snapshot",
                generated_at=generated_at.isoformat(),
                run_id=run_id,
                session=self._session,
                option_root=self.option_root,
                underlying_reference_price=underlying_reference_price,
                expiries=expiry_snapshots,
                contract_count=contract_count,
                status=status,
                stop_reason=stop_reason,
                warning=warning,
            )

    def _rolling_totals(self, state: _ContractState, now: datetime) -> tuple[float, float]:
        self._evict_expired_events(state, now)
        buy_volume = 0.0
        sell_volume = 0.0
        for event in state.events:
            buy_volume += event.buy_volume
            sell_volume += event.sell_volume
        return buy_volume, sell_volume

    def _evict_expired_events(self, state: _ContractState, now: datetime) -> None:
        cutoff = now - self.rolling_window
        while state.events and state.events[0].ts < cutoff:
            state.events.popleft()
