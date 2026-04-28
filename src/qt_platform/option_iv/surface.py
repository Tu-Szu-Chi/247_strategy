from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from math import exp, isfinite
import re
from typing import Any

from qt_platform.option_iv.domain import (
    OptionIvExpirySnapshot,
    OptionIvPoint,
    OptionIvSurfaceSnapshot,
)
from qt_platform.option_iv.pricing import implied_volatility


DATE_CONTRACT_PATTERN = re.compile(r"^(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})$")
MONTH_CONTRACT_PATTERN = re.compile(r"^(?P<year>\d{4})(?P<month>\d{2})$")
WEEKLY_CONTRACT_PATTERN = re.compile(r"^(?P<year>\d{4})(?P<month>\d{2})W(?P<week>\d+)$")
TRADING_DAYS_PER_YEAR = 252.0
DEFAULT_MAX_TICK_AGE_SECONDS = 120.0
MIN_ACCEPTED_IV = 0.01
MAX_ACCEPTED_IV = 3.0
WING_WEIGHT_SIGMA_STEPS = 4.0
SECOND_EXPIRY_SKEW_WEIGHT = 0.75


@dataclass(frozen=True)
class _WeightedIv:
    iv: float
    weight: float


def build_iv_surface(
    *,
    generated_at: datetime,
    underlying_reference_price: float | None,
    underlying_reference_source: str | None,
    expiries: list[Any],
    max_tick_age_seconds: float = DEFAULT_MAX_TICK_AGE_SECONDS,
) -> OptionIvSurfaceSnapshot | None:
    if underlying_reference_price is None or underlying_reference_price <= 0:
        return None

    expiry_snapshots: list[OptionIvExpirySnapshot] = []
    for expiry in expiries:
        contract_month = _read_attr(expiry, "contract_month", "")
        label = _read_attr(expiry, "label", contract_month)
        expiry_at = _expiry_datetime(contract_month)
        if expiry_at is None:
            continue
        time_to_expiry_years = _time_to_expiry_years(generated_at, expiry_at)
        if time_to_expiry_years <= 0:
            continue

        contracts = list(_read_attr(expiry, "contracts", []) or [])
        strike_step = _infer_strike_step(contracts)
        points: list[OptionIvPoint] = []
        call_ivs: list[_WeightedIv] = []
        put_ivs: list[_WeightedIv] = []

        for contract in contracts:
            point = _iv_point(
                contract=contract,
                generated_at=generated_at,
                underlying_reference_price=underlying_reference_price,
                time_to_expiry_years=time_to_expiry_years,
                strike_step=strike_step,
                max_tick_age_seconds=max_tick_age_seconds,
            )
            if point is None:
                continue
            points.append(point)
            weighted = _WeightedIv(
                iv=point.iv,
                weight=_wing_weight(
                    strike_price=point.strike_price,
                    underlying_reference_price=underlying_reference_price,
                    strike_step=strike_step,
                ),
            )
            if point.call_put == "call":
                call_ivs.append(weighted)
            elif point.call_put == "put":
                put_ivs.append(weighted)

        if not points:
            continue
        call_wing_iv = _weighted_average(call_ivs)
        put_wing_iv = _weighted_average(put_ivs)
        skew = call_wing_iv - put_wing_iv if call_wing_iv is not None and put_wing_iv is not None else None
        expiry_snapshots.append(
            OptionIvExpirySnapshot(
                contract_month=contract_month,
                label=label,
                time_to_expiry_years=time_to_expiry_years,
                skew=skew,
                call_wing_iv=call_wing_iv,
                put_wing_iv=put_wing_iv,
                point_count=len(points),
                points=sorted(points, key=lambda item: (item.strike_price, item.call_put, item.instrument_key)),
            )
        )

    if not expiry_snapshots:
        return None
    skew = _surface_skew(expiry_snapshots)

    return OptionIvSurfaceSnapshot(
        generated_at=generated_at.isoformat(),
        underlying_reference_price=underlying_reference_price,
        underlying_reference_source=underlying_reference_source,
        skew=skew,
        skew_intensity=abs(skew) if skew is not None else None,
        expiries=expiry_snapshots,
        status="ready",
    )


def _iv_point(
    *,
    contract: Any,
    generated_at: datetime,
    underlying_reference_price: float,
    time_to_expiry_years: float,
    strike_step: float,
    max_tick_age_seconds: float,
) -> OptionIvPoint | None:
    call_put = str(_read_attr(contract, "call_put", "") or "").lower()
    strike_price = _float_or_none(_read_attr(contract, "strike_price", None))
    last_price = _float_or_none(_read_attr(contract, "last_price", None))
    if call_put not in {"call", "put"} or strike_price is None or last_price is None:
        return None
    if strike_price <= 0 or last_price <= 0:
        return None
    if not _is_otm(call_put=call_put, strike_price=strike_price, underlying_reference_price=underlying_reference_price):
        return None
    if _is_stale(_read_attr(contract, "last_tick_ts", None), generated_at, max_tick_age_seconds):
        return None

    iv = implied_volatility(
        option_price=last_price,
        forward=underlying_reference_price,
        strike=strike_price,
        time_to_expiry_years=time_to_expiry_years,
        call_put=call_put,
    )
    if iv is None or not isfinite(iv) or iv < MIN_ACCEPTED_IV or iv > MAX_ACCEPTED_IV:
        return None

    side = "right_call" if call_put == "call" else "left_put"
    return OptionIvPoint(
        instrument_key=str(_read_attr(contract, "instrument_key", "") or ""),
        symbol=str(_read_attr(contract, "symbol", "") or ""),
        contract_month=str(_read_attr(contract, "contract_month", "") or ""),
        strike_price=strike_price,
        call_put=call_put,
        last_price=last_price,
        iv=iv,
        moneyness=(strike_price - underlying_reference_price) / strike_step,
        side=side,
        last_tick_ts=_read_attr(contract, "last_tick_ts", None),
    )


def _expiry_datetime(contract_month: str) -> datetime | None:
    date_match = DATE_CONTRACT_PATTERN.match(contract_month)
    if date_match:
        return datetime(
            int(date_match.group("year")),
            int(date_match.group("month")),
            int(date_match.group("day")),
            13,
            30,
        )

    weekly_match = WEEKLY_CONTRACT_PATTERN.match(contract_month)
    if weekly_match:
        expiry_date = _nth_weekday(
            year=int(weekly_match.group("year")),
            month=int(weekly_match.group("month")),
            weekday=2,
            occurrence=int(weekly_match.group("week")),
        )
        return datetime.combine(expiry_date, time(hour=13, minute=30))

    month_match = MONTH_CONTRACT_PATTERN.match(contract_month)
    if month_match:
        expiry_date = _nth_weekday(
            year=int(month_match.group("year")),
            month=int(month_match.group("month")),
            weekday=2,
            occurrence=3,
        )
        return datetime.combine(expiry_date, time(hour=13, minute=30))

    return None


def _nth_weekday(*, year: int, month: int, weekday: int, occurrence: int):
    current = datetime(year, month, 1).date()
    while current.weekday() != weekday:
        current += timedelta(days=1)
    return current + timedelta(days=7 * max(occurrence - 1, 0))


def _time_to_expiry_years(generated_at: datetime, expiry_at: datetime) -> float:
    remaining_seconds = (expiry_at - generated_at).total_seconds()
    if remaining_seconds <= 0:
        return 0.0
    return remaining_seconds / (TRADING_DAYS_PER_YEAR * 24 * 60 * 60)


def _infer_strike_step(contracts: list[Any]) -> float:
    strikes = sorted(
        {
            value
            for value in (_float_or_none(_read_attr(contract, "strike_price", None)) for contract in contracts)
            if value is not None and value > 0
        }
    )
    diffs = [right - left for left, right in zip(strikes, strikes[1:]) if right > left]
    return min(diffs) if diffs else 1.0


def _is_otm(*, call_put: str, strike_price: float, underlying_reference_price: float) -> bool:
    if call_put == "call":
        return strike_price > underlying_reference_price
    if call_put == "put":
        return strike_price < underlying_reference_price
    return False


def _is_stale(last_tick_ts: str | None, generated_at: datetime, max_tick_age_seconds: float) -> bool:
    if not last_tick_ts:
        return True
    try:
        tick_ts = datetime.fromisoformat(last_tick_ts)
    except ValueError:
        return True
    return (generated_at - tick_ts).total_seconds() > max_tick_age_seconds


def _wing_weight(*, strike_price: float, underlying_reference_price: float, strike_step: float) -> float:
    distance = abs(strike_price - underlying_reference_price) / max(strike_step, 1.0)
    return exp(-((distance * distance) / (2 * WING_WEIGHT_SIGMA_STEPS * WING_WEIGHT_SIGMA_STEPS)))


def _weighted_average(values: list[_WeightedIv]) -> float | None:
    weight_sum = sum(item.weight for item in values)
    if weight_sum <= 0:
        return None
    return sum(item.iv * item.weight for item in values) / weight_sum


def _surface_skew(expiries: list[OptionIvExpirySnapshot]) -> float | None:
    weighted: list[_WeightedIv] = []
    for index, expiry in enumerate(expiries):
        if expiry.skew is None:
            continue
        weighted.append(
            _WeightedIv(
                iv=expiry.skew,
                weight=1.0 if index == 0 else SECOND_EXPIRY_SKEW_WEIGHT,
            )
        )
    return _weighted_average(weighted)


def _read_attr(value: Any, name: str, default: Any) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)
