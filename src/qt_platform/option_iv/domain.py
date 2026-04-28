from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class OptionIvPoint:
    instrument_key: str
    symbol: str
    contract_month: str
    strike_price: float
    call_put: str
    last_price: float
    iv: float
    moneyness: float
    side: str
    last_tick_ts: str | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class OptionIvExpirySnapshot:
    contract_month: str
    label: str
    time_to_expiry_years: float
    skew: float | None
    call_wing_iv: float | None
    put_wing_iv: float | None
    point_count: int
    points: list[OptionIvPoint]

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["points"] = [point.to_dict() for point in self.points]
        return payload


@dataclass(frozen=True)
class OptionIvSurfaceSnapshot:
    generated_at: str
    underlying_reference_price: float | None
    underlying_reference_source: str | None
    skew: float | None
    skew_intensity: float | None
    expiries: list[OptionIvExpirySnapshot]
    status: str
    warning: str | None = None

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["expiries"] = [expiry.to_dict() for expiry in self.expiries]
        return payload
