from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import re
from threading import Lock

from qt_platform.domain import CanonicalTick
from qt_platform.option_iv.surface import build_iv_surface
from qt_platform.option_power.domain import (
    OptionContractSnapshot,
    OptionExpirySnapshot,
    OptionPowerSnapshot,
)
from qt_platform.regime import RegimeFeatureSnapshot


MONTH_CONTRACT_PATTERN = re.compile(r"^(?P<year>\d{4})(?P<month>\d{2})$")
DATE_CONTRACT_PATTERN = re.compile(r"^(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})$")
WEEKLY_CONTRACT_PATTERN = re.compile(r"^(?P<year>\d{4})(?P<month>\d{2})W(?P<week>\d+)$")
BASE_PRESSURE_BUY_WEIGHT = 1.0
BASE_PRESSURE_SELL_WEIGHT = 1.0
WEIGHTED_PRESSURE_BUY_WEIGHT = 1.0
WEIGHTED_PRESSURE_SELL_WEIGHT = 1.2
PRESSURE_SIGMA = 2.0
SECOND_EXPIRY_WEIGHT = 0.75


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
    rolling_buy_volume: float = 0.0
    rolling_sell_volume: float = 0.0
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

    def set_option_root(self, option_root: str) -> None:
        with self._lock:
            self.option_root = option_root

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
            state.rolling_buy_volume += buy_volume
            state.rolling_sell_volume += sell_volume
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
        underlying_reference_source: str | None,
        status: str,
        regime: RegimeFeatureSnapshot | None = None,
        stop_reason: str | None = None,
        warning: str | None = None,
    ) -> OptionPowerSnapshot:
        with self._lock:
            pressure_metrics = _compute_pressure_metrics(
                states=list(self._states.values()),
                underlying_reference_price=underlying_reference_price,
            )
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
                    label=_format_expiry_label(contract_month),
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
            iv_surface = build_iv_surface(
                generated_at=generated_at,
                underlying_reference_price=underlying_reference_price,
                underlying_reference_source=underlying_reference_source,
                expiries=expiry_snapshots,
            )

            return OptionPowerSnapshot(
                type="option_power_snapshot",
                generated_at=generated_at.isoformat(),
                run_id=run_id,
                session=self._session,
                option_root=self.option_root,
                underlying_reference_price=underlying_reference_price,
                underlying_reference_source=underlying_reference_source,
                raw_pressure=pressure_metrics["raw_pressure"],
                pressure_index=pressure_metrics["pressure_index"],
                raw_pressure_weighted=pressure_metrics["raw_pressure_weighted"],
                pressure_index_weighted=pressure_metrics["pressure_index_weighted"],
                expiries=expiry_snapshots,
                contract_count=contract_count,
                status=status,
                regime=regime,
                iv_surface=iv_surface,
                stop_reason=stop_reason,
                warning=warning,
            )

    def _rolling_totals(self, state: _ContractState, now: datetime) -> tuple[float, float]:
        self._evict_expired_events(state, now)
        return state.rolling_buy_volume, state.rolling_sell_volume

    def _evict_expired_events(self, state: _ContractState, now: datetime) -> None:
        cutoff = now - self.rolling_window
        while state.events and state.events[0].ts < cutoff:
            event = state.events.popleft()
            state.rolling_buy_volume -= event.buy_volume
            state.rolling_sell_volume -= event.sell_volume


def _format_expiry_label(contract_month: str) -> str:
    weekly_match = WEEKLY_CONTRACT_PATTERN.match(contract_month)
    if weekly_match:
        year = weekly_match.group("year")
        month = weekly_match.group("month")
        week = weekly_match.group("week")
        return f"{year}-{month} W{week}"

    date_match = DATE_CONTRACT_PATTERN.match(contract_month)
    if date_match:
        year = date_match.group("year")
        month = date_match.group("month")
        day = date_match.group("day")
        return f"{year}-{month}-{day}"

    month_match = MONTH_CONTRACT_PATTERN.match(contract_month)
    if month_match:
        year = month_match.group("year")
        month = month_match.group("month")
        return f"{year}-{month}"

    return contract_month


def _compute_pressure_metrics(
    *,
    states: list[_ContractState],
    underlying_reference_price: float | None,
) -> dict[str, int]:
    if not states or underlying_reference_price is None:
        return {
            "raw_pressure": 0,
            "pressure_index": 0,
            "raw_pressure_weighted": 0,
            "pressure_index_weighted": 0,
        }

    strike_step = _infer_strike_step(states)
    expiry_weights = _expiry_weights(states)
    raw_score_sum = 0.0
    raw_abs_sum = 0.0
    weighted_raw_score_sum = 0.0
    weighted_raw_abs_sum = 0.0

    for state in states:
        distance = abs(state.strike_price - underlying_reference_price) / strike_step
        expiry_weight = expiry_weights.get(state.contract_month, SECOND_EXPIRY_WEIGHT)
        contract_weight = expiry_weight * _gaussian_weight(distance)
        buy_volume = state.cumulative_buy_volume
        sell_volume = state.cumulative_sell_volume
        raw_score_sum += contract_weight * _directional_flow(
            call_put=state.call_put,
            buy_volume=buy_volume,
            sell_volume=sell_volume,
            buy_weight=BASE_PRESSURE_BUY_WEIGHT,
            sell_weight=BASE_PRESSURE_SELL_WEIGHT,
        )
        raw_abs_sum += contract_weight * (
            BASE_PRESSURE_BUY_WEIGHT * buy_volume + BASE_PRESSURE_SELL_WEIGHT * sell_volume
        )
        weighted_raw_score_sum += contract_weight * _directional_flow(
            call_put=state.call_put,
            buy_volume=buy_volume,
            sell_volume=sell_volume,
            buy_weight=WEIGHTED_PRESSURE_BUY_WEIGHT,
            sell_weight=WEIGHTED_PRESSURE_SELL_WEIGHT,
        )
        weighted_raw_abs_sum += contract_weight * (
            WEIGHTED_PRESSURE_BUY_WEIGHT * buy_volume + WEIGHTED_PRESSURE_SELL_WEIGHT * sell_volume
        )

    return {
        "raw_pressure": round(raw_score_sum),
        "pressure_index": _normalized_pressure(raw_score_sum, raw_abs_sum),
        "raw_pressure_weighted": round(weighted_raw_score_sum),
        "pressure_index_weighted": _normalized_pressure(weighted_raw_score_sum, weighted_raw_abs_sum),
    }


def _infer_strike_step(states: list[_ContractState]) -> float:
    strikes = sorted({state.strike_price for state in states})
    if len(strikes) < 2:
        return 1.0

    positive_diffs = [curr - prev for prev, curr in zip(strikes, strikes[1:]) if curr > prev]
    if not positive_diffs:
        return 1.0
    return min(positive_diffs)


def _expiry_weights(states: list[_ContractState]) -> dict[str, float]:
    ordered_contract_months = sorted({state.contract_month for state in states})
    if not ordered_contract_months:
        return {}
    weights = {ordered_contract_months[0]: 1.0}
    for contract_month in ordered_contract_months[1:]:
        weights[contract_month] = SECOND_EXPIRY_WEIGHT
    return weights


def _gaussian_weight(distance: float) -> float:
    return pow(2.718281828459045, -((distance * distance) / (2 * PRESSURE_SIGMA * PRESSURE_SIGMA)))


def _directional_flow(
    *,
    call_put: str,
    buy_volume: float,
    sell_volume: float,
    buy_weight: float,
    sell_weight: float,
) -> float:
    normalized = (call_put or "").strip().lower()
    if normalized == "put":
        return sell_weight * sell_volume - buy_weight * buy_volume
    return buy_weight * buy_volume - sell_weight * sell_volume


def _normalized_pressure(score_sum: float, abs_sum: float) -> int:
    if abs_sum <= 0:
        return 0
    return round(100 * score_sum / abs_sum)
