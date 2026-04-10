from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta

from qt_platform.storage.base import BarRepository
from qt_platform.symbol_registry import SymbolRegistryEntry


@dataclass(frozen=True)
class SyncPlanItem:
    symbol: str
    root_symbol: str
    market: str
    instrument_type: str
    timeframe: str
    mode: str
    request_strategy: str
    existing_trading_days: int
    missing_dates: list[date]
    estimated_requests: int
    notes: list[str]


@dataclass(frozen=True)
class SyncPlan:
    registry_symbols: int
    requested_dates: int
    start_date: date
    end_date: date
    requests_per_hour: int
    target_utilization: float
    usable_requests_per_hour: int
    total_estimated_requests: int
    estimated_runtime_minutes: float
    timeframe_totals: dict[str, dict]
    items: list[SyncPlanItem]

    def to_dict(self) -> dict:
        payload = asdict(self)
        for item in payload["items"]:
            item["missing_dates"] = [value.isoformat() for value in item["missing_dates"]]
        for timeframe_total in payload["timeframe_totals"].values():
            if "request_dates" in timeframe_total:
                timeframe_total["request_dates"] = [value.isoformat() for value in timeframe_total["request_dates"]]
        payload["start_date"] = self.start_date.isoformat()
        payload["end_date"] = self.end_date.isoformat()
        return payload


def plan_sync(
    store: BarRepository,
    entries: list[SymbolRegistryEntry],
    start_date: date,
    end_date: date,
    timeframes: list[str],
    requests_per_hour: int,
    target_utilization: float,
) -> SyncPlan:
    request_dates = _inclusive_dates(start_date, end_date)
    items: list[SyncPlanItem] = []
    request_totals: dict[str, int] = {}
    request_dates_by_strategy: dict[str, set[date]] = {}

    for entry in entries:
        for timeframe in timeframes:
            item = _plan_item(store, entry, timeframe, request_dates)
            items.append(item)
            request_totals[item.request_strategy] = request_totals.get(item.request_strategy, 0) + item.estimated_requests
            if item.request_strategy == "bulk_daily_all_symbols":
                request_dates_by_strategy.setdefault(item.request_strategy, set()).update(item.missing_dates)

    bulk_daily_requests = len(request_dates_by_strategy.get("bulk_daily_all_symbols", set()))
    per_symbol_range_requests = request_totals.get("per_symbol_range", 0)
    per_symbol_per_day_tick_requests = request_totals.get("per_symbol_per_day_tick", 0)
    per_symbol_per_day_chain_requests = request_totals.get("per_symbol_per_day_chain", 0)
    total_requests = (
        bulk_daily_requests
        + per_symbol_range_requests
        + per_symbol_per_day_tick_requests
        + per_symbol_per_day_chain_requests
    )
    usable_requests_per_hour = max(1, int(requests_per_hour * target_utilization))

    return SyncPlan(
        registry_symbols=len(entries),
        requested_dates=len(request_dates),
        start_date=start_date,
        end_date=end_date,
        requests_per_hour=requests_per_hour,
        target_utilization=target_utilization,
        usable_requests_per_hour=usable_requests_per_hour,
        total_estimated_requests=total_requests,
        estimated_runtime_minutes=round(total_requests / usable_requests_per_hour * 60, 2),
        timeframe_totals={
            "1d": {
                "strategy_breakdown": {
                    "bulk_daily_all_symbols": {
                        "estimated_requests": bulk_daily_requests,
                        "request_dates": sorted(request_dates_by_strategy.get("bulk_daily_all_symbols", set())),
                    },
                    "per_symbol_range": {
                        "estimated_requests": per_symbol_range_requests,
                    },
                    "per_symbol_per_day_chain": {
                        "estimated_requests": per_symbol_per_day_chain_requests,
                    },
                },
                "estimated_requests": bulk_daily_requests + per_symbol_range_requests + per_symbol_per_day_chain_requests,
            },
            "1m": {
                "strategy": "per_symbol_per_day_tick",
                "estimated_requests": per_symbol_per_day_tick_requests,
            },
        },
        items=items,
    )


def _plan_item(
    store: BarRepository,
    entry: SymbolRegistryEntry,
    timeframe: str,
    request_dates: list[date],
) -> SyncPlanItem:
    existing_days = set(store.list_trading_days(timeframe, entry.root_symbol, request_dates[0], request_dates[-1]))
    missing_dates = [day for day in request_dates if day not in existing_days]
    latest_overall = store.latest_bar_ts(timeframe, entry.root_symbol)

    if latest_overall is None:
        mode = "bootstrap"
    elif not missing_dates:
        mode = "up_to_date"
    elif not existing_days:
        mode = "catch_up" if request_dates[0] > latest_overall.date() else "repair"
    elif all(day > max(existing_days) for day in missing_dates):
        mode = "catch_up"
    else:
        mode = "repair"

    notes: list[str] = []
    strategy = _request_strategy(entry, timeframe)
    if strategy == "bulk_daily_all_symbols":
        notes.append("Daily sync can use one bulk request per date across all registry symbols.")
    elif strategy == "per_symbol_range":
        notes.append("Daily sync is estimated as one range request per symbol.")
    elif strategy == "per_symbol_per_day_chain":
        notes.append("Option daily sync is estimated as one request per symbol per date.")
    if timeframe == "1m" and existing_days:
        notes.append("Minute plan only checks trading_day presence, not intraday missing bars.")

    return SyncPlanItem(
        symbol=entry.symbol,
        root_symbol=entry.root_symbol,
        market=entry.market,
        instrument_type=entry.instrument_type,
        timeframe=timeframe,
        mode=mode,
        request_strategy=strategy,
        existing_trading_days=len(existing_days),
        missing_dates=missing_dates,
        estimated_requests=_estimated_requests(strategy, missing_dates),
        notes=notes,
    )


def _inclusive_dates(start_date: date, end_date: date) -> list[date]:
    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date.")
    days: list[date] = []
    current = start_date
    while current <= end_date:
        days.append(current)
        current += timedelta(days=1)
    return days


def _request_strategy(entry: SymbolRegistryEntry, timeframe: str) -> str:
    if timeframe == "1m":
        return "per_symbol_per_day_tick"
    if entry.market == "TAIFEX" and entry.instrument_type == "future":
        return "bulk_daily_all_symbols"
    if entry.market == "TWSE" and entry.instrument_type == "stock":
        return "per_symbol_range"
    if entry.market == "TAIFEX" and entry.instrument_type == "option":
        return "per_symbol_per_day_chain"
    return "unsupported"


def _estimated_requests(strategy: str, missing_dates: list[date]) -> int:
    if not missing_dates:
        return 0
    if strategy == "bulk_daily_all_symbols":
        return 0
    if strategy == "per_symbol_range":
        return 1
    if strategy in {"per_symbol_per_day_tick", "per_symbol_per_day_chain"}:
        return len(missing_dates)
    return len(missing_dates)
