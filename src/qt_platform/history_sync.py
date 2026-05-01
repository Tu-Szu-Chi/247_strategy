from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Callable

from qt_platform.maintenance.service import MaintenanceService
from qt_platform.providers.base import BaseProvider
from qt_platform.storage.base import BarRepository
from qt_platform.symbol_registry import SymbolRegistryEntry


@dataclass(frozen=True)
class HistorySyncItem:
    symbol: str
    timeframe: str
    trading_day: date
    action: str
    rows_upserted: int
    message: str | None = None


@dataclass(frozen=True)
class HistorySyncResult:
    start_date: date
    end_date: date
    total_candidates: int
    processed: int
    synced: int
    skipped: int
    failed: int
    items: list[HistorySyncItem]

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["start_date"] = self.start_date.isoformat()
        payload["end_date"] = self.end_date.isoformat()
        for item in payload["items"]:
            item["trading_day"] = item["trading_day"].isoformat()
        return payload


def build_history_entries(registry_entries: list[SymbolRegistryEntry]) -> list[SymbolRegistryEntry]:
    entries_by_key: dict[tuple[str, str], SymbolRegistryEntry] = {}
    for entry in registry_entries:
        if entry.instrument_type not in {"stock", "future", "index"}:
            continue
        entries_by_key[(entry.root_symbol, entry.instrument_type)] = SymbolRegistryEntry(
            symbol=entry.symbol,
            root_symbol=entry.root_symbol,
            market=entry.market,
            instrument_type=entry.instrument_type,
        )
    return list(entries_by_key.values())


def sync_history_days(
    store: BarRepository,
    provider: BaseProvider,
    entries: list[SymbolRegistryEntry],
    start_date: date,
    end_date: date,
    timeframes: list[str],
    session_scope: str = "day_and_night",
    progress_callback: Callable[[dict], None] | None = None,
) -> HistorySyncResult:
    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date.")

    requested_days = _inclusive_dates(start_date, end_date)
    supported_entries = [
        entry for entry in entries
        if any(
            provider.supports_history(
                market=entry.market,
                instrument_type=entry.instrument_type,
                symbol=entry.root_symbol,
                timeframe=timeframe,
            )
            for timeframe in timeframes
        )
    ]
    total_candidates = len(requested_days) * len(timeframes) * len(supported_entries)
    items: list[HistorySyncItem] = []
    processed = 0
    synced = 0
    skipped = 0
    failed = 0
    service = MaintenanceService(provider=provider, store=store)
    existing_days_by_key = _existing_days_by_symbol(store, supported_entries, timeframes, start_date, end_date)

    for timeframe in timeframes:
        for entry in supported_entries:
            if not provider.supports_history(
                market=entry.market,
                instrument_type=entry.instrument_type,
                symbol=entry.root_symbol,
                timeframe=timeframe,
            ):
                continue
            existing_days = existing_days_by_key[(timeframe, entry.root_symbol)]
            for trading_day in requested_days:
                payload = {
                    "timeframe": timeframe,
                    "symbol": entry.root_symbol,
                    "trading_day": trading_day.isoformat(),
                    "source": "finmind",
                }
                if trading_day in existing_days:
                    skipped += 1
                    processed += 1
                    item = HistorySyncItem(
                        symbol=entry.root_symbol,
                        timeframe=timeframe,
                        trading_day=trading_day,
                        action="skipped",
                        rows_upserted=0,
                        message="existing_trading_day",
                    )
                    items.append(item)
                    _emit_history_progress(
                        progress_callback,
                        status="history_day_skipped",
                        processed=processed,
                        total_candidates=total_candidates,
                        synced=synced,
                        skipped=skipped,
                        failed=failed,
                        rows_upserted=0,
                        action="skipped",
                        message="existing_trading_day",
                        **payload,
                    )
                    continue

                _emit_history_progress(
                    progress_callback,
                    status="history_day_started",
                    processed=processed,
                    total_candidates=total_candidates,
                    synced=synced,
                    skipped=skipped,
                    failed=failed,
                    action="started",
                    **payload,
                )
                try:
                    rows_upserted = service.backfill(
                        symbol=entry.root_symbol,
                        start_date=trading_day,
                        end_date=trading_day,
                        timeframe=timeframe,
                        session_scope=session_scope,
                    )
                    existing_days.add(trading_day)
                    synced += 1
                    action = "synced"
                    message = None
                except Exception as exc:
                    rows_upserted = 0
                    failed += 1
                    action = "failed"
                    message = str(exc)
                processed += 1
                item = HistorySyncItem(
                    symbol=entry.root_symbol,
                    timeframe=timeframe,
                    trading_day=trading_day,
                    action=action,
                    rows_upserted=rows_upserted,
                    message=message,
                )
                items.append(item)
                _emit_history_progress(
                    progress_callback,
                    status=f"history_day_{action}",
                    processed=processed,
                    total_candidates=total_candidates,
                    synced=synced,
                    skipped=skipped,
                    failed=failed,
                    rows_upserted=rows_upserted,
                    action=action,
                    message=message,
                    **payload,
                )

    return HistorySyncResult(
        start_date=start_date,
        end_date=end_date,
        total_candidates=total_candidates,
        processed=processed,
        synced=synced,
        skipped=skipped,
        failed=failed,
        items=items,
    )


def _existing_days_by_symbol(
    store: BarRepository,
    entries: list[SymbolRegistryEntry],
    timeframes: list[str],
    start_date: date,
    end_date: date,
) -> dict[tuple[str, str], set[date]]:
    payload: dict[tuple[str, str], set[date]] = {}
    for timeframe in timeframes:
        for entry in entries:
            payload[(timeframe, entry.root_symbol)] = set(
                store.list_trading_days(timeframe, entry.root_symbol, start_date, end_date)
            )
    return payload


def _inclusive_dates(start_date: date, end_date: date) -> list[date]:
    days: list[date] = []
    current = start_date
    while current <= end_date:
        days.append(current)
        current += timedelta(days=1)
    return days


def _emit_history_progress(progress_callback: Callable[[dict], None] | None, **payload: object) -> None:
    if progress_callback is None:
        return
    progress_callback(payload)
