from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any


BASE_PRESSURE_BUY_WEIGHT = 1.0
BASE_PRESSURE_SELL_WEIGHT = 1.0
WEIGHTED_PRESSURE_BUY_WEIGHT = 1.0
WEIGHTED_PRESSURE_SELL_WEIGHT = 1.2
PRESSURE_SIGMA = 2.0
SECOND_EXPIRY_WEIGHT = 0.75


@dataclass(frozen=True)
class PressureContractInput:
    contract_month: str
    strike_price: float
    call_put: str
    cumulative_buy_volume: float
    cumulative_sell_volume: float


def directional_flow(
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


def compute_pressure_metrics(
    *,
    contracts: Iterable[PressureContractInput | Mapping[str, Any]],
    underlying_reference_price: float | None,
) -> dict[str, int]:
    contract_items = [_coerce_pressure_contract(item) for item in contracts]
    if not contract_items or underlying_reference_price is None:
        return {
            "raw_pressure": 0,
            "pressure_index": 0,
            "raw_pressure_weighted": 0,
            "pressure_index_weighted": 0,
        }

    strike_step = _infer_strike_step(contract_items)
    expiry_weights = _expiry_weights(contract_items)

    raw_score_sum = 0.0
    raw_abs_sum = 0.0
    weighted_raw_score_sum = 0.0
    weighted_raw_abs_sum = 0.0

    for contract in contract_items:
        buy_volume = contract.cumulative_buy_volume
        sell_volume = contract.cumulative_sell_volume
        
        strike_dist = (contract.strike_price - underlying_reference_price) / strike_step
        contract_weight = _gaussian_weight(strike_dist) * expiry_weights.get(contract.contract_month, 1.0)
        
        # Raw
        raw_score_sum += contract_weight * (BASE_PRESSURE_BUY_WEIGHT * buy_volume - BASE_PRESSURE_SELL_WEIGHT * sell_volume)
        raw_abs_sum += contract_weight * (BASE_PRESSURE_BUY_WEIGHT * buy_volume + BASE_PRESSURE_SELL_WEIGHT * sell_volume)
        
        # Weighted
        weighted_raw_score_sum += contract_weight * (
            WEIGHTED_PRESSURE_BUY_WEIGHT * buy_volume - WEIGHTED_PRESSURE_SELL_WEIGHT * sell_volume
        )
        weighted_raw_abs_sum += contract_weight * (
            WEIGHTED_PRESSURE_BUY_WEIGHT * buy_volume + WEIGHTED_PRESSURE_SELL_WEIGHT * sell_volume
        )

    return {
        "raw_pressure": round(raw_score_sum),
        "pressure_index": normalized_pressure(raw_score_sum, raw_abs_sum),
        "raw_pressure_weighted": round(weighted_raw_score_sum),
        "pressure_index_weighted": normalized_pressure(weighted_raw_score_sum, weighted_raw_abs_sum),
    }


def normalized_pressure(score_sum: float, abs_sum: float) -> int:
    if abs_sum <= 0:
        return 0
    return round((score_sum / abs_sum) * 100)


def _coerce_pressure_contract(item: PressureContractInput | Mapping[str, Any]) -> PressureContractInput:
    if isinstance(item, PressureContractInput):
        return item
    return PressureContractInput(
        contract_month=str(item.get("contract_month") or ""),
        strike_price=float(item.get("strike_price") or 0.0),
        call_put=str(item.get("call_put") or ""),
        cumulative_buy_volume=float(item.get("cumulative_buy_volume") or item.get("buy_volume") or 0.0),
        cumulative_sell_volume=float(item.get("cumulative_sell_volume") or item.get("sell_volume") or 0.0),
    )


def _infer_strike_step(contracts: Sequence[PressureContractInput]) -> float:
    strikes = sorted({contract.strike_price for contract in contracts})
    if len(strikes) < 2:
        return 1.0
    diffs = [curr - prev for prev, curr in zip(strikes, strikes[1:]) if curr > prev]
    return min(diffs) if diffs else 1.0


def _expiry_weights(contracts: Sequence[PressureContractInput]) -> dict[str, float]:
    ordered_months = sorted({contract.contract_month for contract in contracts})
    if not ordered_months:
        return {}
    weights = {ordered_months[0]: 1.0}
    for m in ordered_months[1:]:
        weights[m] = SECOND_EXPIRY_WEIGHT
    return weights


def _gaussian_weight(distance: float) -> float:
    return pow(2.718281828459045, -((distance * distance) / (2 * PRESSURE_SIGMA * PRESSURE_SIGMA)))
