from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class Bar:
    ts: datetime
    trading_day: date
    symbol: str
    contract_month: str
    session: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    open_interest: float | None
    source: str
    up_ticks: float | None = None
    down_ticks: float | None = None
    instrument_key: str | None = None
    strike_price: float | None = None
    call_put: str | None = None
    build_source: str = "historical"


@dataclass(frozen=True)
class CanonicalTick:
    ts: datetime
    trading_day: date
    symbol: str
    price: float
    size: float
    source: str
    session: str
    instrument_key: str | None = None
    contract_month: str = ""
    strike_price: float | None = None
    call_put: str | None = None
    tick_direction: str | None = None
    total_volume: float | None = None
    bid_side_total_vol: float | None = None
    ask_side_total_vol: float | None = None
    payload_json: str | None = None


@dataclass(frozen=True)
class Signal:
    ts: datetime
    side: Side
    size: int = 1
    reason: str = ""


@dataclass(frozen=True)
class Fill:
    ts: datetime
    side: Side
    price: float
    size: int
    reason: str = ""


@dataclass(frozen=True)
class Trade:
    entry_ts: datetime
    exit_ts: datetime
    side: Side
    entry_price: float
    exit_price: float
    size: int

    @property
    def pnl(self) -> float:
        direction = 1 if self.side == Side.BUY else -1
        return (self.exit_price - self.entry_price) * direction * self.size


@dataclass(frozen=True)
class Gap:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class LiveRunMetadata:
    run_id: str
    provider: str
    mode: str
    started_at: datetime
    session_scope: str
    topic_count: int
    symbols_json: str
    codes_json: str | None = None
    option_root: str | None = None
    underlying_future_symbol: str | None = None
    expiry_count: int | None = None
    atm_window: int | None = None
    call_put: str | None = None
    reference_price: float | None = None
    status: str = "started"


@dataclass
class BacktestResult:
    starting_cash: float
    ending_cash: float
    equity_curve: list[tuple[datetime, float]]
    fills: list[Fill]
    trades: list[Trade]
    metrics: dict[str, Any] = field(default_factory=dict)
