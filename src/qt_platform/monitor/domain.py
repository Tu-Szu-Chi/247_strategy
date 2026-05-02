from __future__ import annotations

from dataclasses import asdict, dataclass

from qt_platform.option_iv.domain import OptionIvSurfaceSnapshot
from qt_platform.market_state.mtx import RegimeFeatureSnapshot


@dataclass(frozen=True)
class MonitorContractSnapshot:
    instrument_key: str
    symbol: str
    contract_month: str
    strike_price: float
    call_put: str
    last_price: float | None
    cumulative_buy_volume: float
    cumulative_sell_volume: float
    cumulative_power: float
    rolling_1m_buy_volume: float
    rolling_1m_sell_volume: float
    power_1m_delta: float
    unknown_volume: float
    last_tick_ts: str | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class MonitorExpirySnapshot:
    contract_month: str
    label: str
    contracts: list[MonitorContractSnapshot]

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["contracts"] = [contract.to_dict() for contract in self.contracts]
        return payload


@dataclass(frozen=True)
class MonitorSnapshot:
    type: str
    generated_at: str
    run_id: str | None
    session: str
    option_root: str
    underlying_reference_price: float | None
    underlying_reference_source: str | None
    raw_pressure: int
    pressure_index: int
    raw_pressure_weighted: int
    pressure_index_weighted: int
    expiries: list[MonitorExpirySnapshot]
    contract_count: int
    status: str
    regime: RegimeFeatureSnapshot | None = None
    iv_surface: OptionIvSurfaceSnapshot | None = None
    stop_reason: str | None = None
    warning: str | None = None

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["expiries"] = [expiry.to_dict() for expiry in self.expiries]
        payload["regime"] = self.regime.to_dict() if self.regime else None
        payload["iv_surface"] = self.iv_surface.to_dict() if self.iv_surface else None
        return payload
