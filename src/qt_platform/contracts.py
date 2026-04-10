from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from qt_platform.domain import Bar


@dataclass(frozen=True)
class ContractResolution:
    root_symbol: str
    contract_month: str
    effective_trading_day: date
    last_trading_day: date


def resolve_mtx_monthly_contract(target: date | datetime) -> ContractResolution:
    trading_day = target.date() if isinstance(target, datetime) else target
    contract_month_date = date(trading_day.year, trading_day.month, 1)
    last_trading_day = third_wednesday(contract_month_date.year, contract_month_date.month)
    if trading_day > last_trading_day:
        contract_month_date = _next_month(contract_month_date)
        last_trading_day = third_wednesday(contract_month_date.year, contract_month_date.month)
    return ContractResolution(
        root_symbol="MTX",
        contract_month=f"{contract_month_date.year:04d}{contract_month_date.month:02d}",
        effective_trading_day=trading_day,
        last_trading_day=last_trading_day,
    )


def root_symbol_for(symbol: str) -> str:
    if symbol == "MTX_MAIN":
        return "MTX"
    return symbol


def is_continuous_symbol(symbol: str) -> bool:
    return symbol == "MTX_MAIN"


def select_symbol_view(symbol: str, bars: list[Bar]) -> list[Bar]:
    if symbol != "MTX_MAIN":
        return bars
    selected: list[Bar] = []
    for bar in bars:
        resolution = resolve_mtx_monthly_contract(bar.trading_day)
        if bar.contract_month == resolution.contract_month:
            selected.append(bar)
    return selected


def third_wednesday(year: int, month: int) -> date:
    first_day = date(year, month, 1)
    days_until_wed = (2 - first_day.weekday()) % 7
    first_wednesday = first_day + timedelta(days=days_until_wed)
    return first_wednesday + timedelta(weeks=2)


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)
