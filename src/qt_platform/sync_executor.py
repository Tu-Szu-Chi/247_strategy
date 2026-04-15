from __future__ import annotations

import concurrent.futures
from dataclasses import asdict, dataclass
from datetime import date
from typing import Callable

from qt_platform.maintenance.service import MaintenanceService
from qt_platform.providers.base import BaseProvider
from qt_platform.storage.base import BarRepository
from qt_platform.symbol_registry import SymbolRegistryEntry
from qt_platform.sync_planner import SyncPlan, SyncPlanItem, plan_sync


@dataclass(frozen=True)
class SyncExecutionItem:
    symbol: str
    root_symbol: str
    market: str
    instrument_type: str
    timeframe: str
    mode: str
    action: str
    requested_start_date: date | None
    requested_end_date: date | None
    upserted_bars: int
    estimated_requests: int
    notes: list[str]


@dataclass(frozen=True)
class SyncExecutionResult:
    plan: SyncPlan
    items: list[SyncExecutionItem]

    def to_dict(self) -> dict:
        payload = {
            "plan": self.plan.to_dict(),
            "items": [asdict(item) for item in self.items],
        }
        for item in payload["items"]:
            if item["requested_start_date"] is not None:
                item["requested_start_date"] = item["requested_start_date"].isoformat()
            if item["requested_end_date"] is not None:
                item["requested_end_date"] = item["requested_end_date"].isoformat()
        return payload


def sync_registry(
    store: BarRepository,
    provider: BaseProvider,
    entries: list[SymbolRegistryEntry],
    start_date: date,
    end_date: date,
    timeframes: list[str],
    requests_per_hour: int,
    target_utilization: float,
    session_scope: str = "day_and_night",
    allow_repair: bool = False,
    progress_callback: Callable[[dict], None] | None = None,
) -> SyncExecutionResult:
    plan = plan_sync(
        store=store,
        entries=entries,
        start_date=start_date,
        end_date=end_date,
        timeframes=timeframes,
        requests_per_hour=requests_per_hour,
        target_utilization=target_utilization,
    )
    service = MaintenanceService(provider=provider, store=store)
    results: list[SyncExecutionItem] = []

    for timeframe in timeframes:
        timeframe_items = [item for item in plan.items if item.timeframe == timeframe]
        bulk_candidates = [
            item
            for item in timeframe_items
            if item.request_strategy == "bulk_daily_all_symbols"
            and item.mode in {"bootstrap", "catch_up"}
            and item.missing_dates
            and provider.supports_history(
                market=item.market,
                instrument_type=item.instrument_type,
                symbol=item.root_symbol,
                timeframe=timeframe,
            )
        ]
        if bulk_candidates:
            results.extend(
                _execute_bulk_daily(
                    store=store,
                    provider=provider,
                    items=bulk_candidates,
                    session_scope=session_scope,
                    start_date=min(item.missing_dates[0] for item in bulk_candidates),
                    end_date=max(item.missing_dates[-1] for item in bulk_candidates),
                    timeframe=timeframe,
                    progress_callback=progress_callback,
                )
            )

        bulk_item_keys = {
            (item.root_symbol, item.market, item.instrument_type, item.timeframe)
            for item in bulk_candidates
        }
        
        non_bulk_items = [
            item for item in timeframe_items
            if (item.root_symbol, item.market, item.instrument_type, item.timeframe) not in bulk_item_keys
        ]

        if non_bulk_items:
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = []
                for item in non_bulk_items:
                    futures.append(
                        executor.submit(
                            _execute_item,
                            service=service,
                            provider=provider,
                            item=item,
                            session_scope=session_scope,
                            allow_repair=allow_repair,
                            progress_callback=progress_callback,
                        )
                    )
                for future in concurrent.futures.as_completed(futures):
                    results.append(future.result())

    return SyncExecutionResult(plan=plan, items=results)


def _execute_bulk_daily(
    store: BarRepository,
    provider: BaseProvider,
    items: list[SyncPlanItem],
    session_scope: str,
    start_date: date,
    end_date: date,
    timeframe: str,
    progress_callback: Callable[[dict], None] | None = None,
) -> list[SyncExecutionItem]:
    grouped_entries = {
        (item.root_symbol, item.market, item.instrument_type): item for item in items
    }
    symbols = sorted({item.root_symbol for item in items})
    market = items[0].market
    if progress_callback is not None:
        progress_callback(
            {
                "status": "history_item_started",
                "mode": "bulk_daily",
                "market": market,
                "instrument_type": items[0].instrument_type,
                "timeframe": timeframe,
                "symbols": symbols,
                "requested_start_date": start_date.isoformat(),
                "requested_end_date": end_date.isoformat(),
            }
        )
    batches = provider.fetch_history_batch(
        market=market,
        symbols=symbols,
        start_date=start_date,
        end_date=end_date,
        timeframe=timeframe,
        session_scope=session_scope,
    )

    results: list[SyncExecutionItem] = []
    for symbol in symbols:
        bars = batches.get(symbol, [])
        upserted = store.upsert_bars(timeframe, bars)
        cursor_ts = bars[-1].ts if bars else None
        store.update_sync_cursor(
            source="finmind",
            symbol=symbol,
            timeframe=timeframe,
            session_scope=session_scope,
            cursor_ts=cursor_ts,
        )
        plan_item = grouped_entries[(symbol, market, items[0].instrument_type)]
        results.append(
            SyncExecutionItem(
                symbol=plan_item.symbol,
                root_symbol=symbol,
                market=market,
                instrument_type=plan_item.instrument_type,
                timeframe=timeframe,
                mode=plan_item.mode,
                action="synced",
                requested_start_date=start_date,
                requested_end_date=end_date,
                upserted_bars=upserted,
                estimated_requests=0,
                notes=["Executed through provider batch daily fetch."],
            )
        )
        if progress_callback is not None:
            progress_callback(
                {
                    "status": "history_item_completed",
                    "mode": "bulk_daily",
                    "symbol": plan_item.symbol,
                    "root_symbol": symbol,
                    "market": market,
                    "instrument_type": plan_item.instrument_type,
                    "timeframe": timeframe,
                    "requested_start_date": start_date.isoformat(),
                    "requested_end_date": end_date.isoformat(),
                    "upserted_bars": upserted,
                    "action": "synced",
                }
            )
    return results


def _execute_item(
    service: MaintenanceService,
    provider: BaseProvider,
    item: SyncPlanItem,
    session_scope: str,
    allow_repair: bool,
    progress_callback: Callable[[dict], None] | None = None,
) -> SyncExecutionItem:
    if not provider.supports_history(
        market=item.market,
        instrument_type=item.instrument_type,
        symbol=item.root_symbol,
        timeframe=item.timeframe,
    ):
        return SyncExecutionItem(
            symbol=item.symbol,
            root_symbol=item.root_symbol,
            market=item.market,
            instrument_type=item.instrument_type,
            timeframe=item.timeframe,
            mode=item.mode,
            action="skipped_unsupported",
            requested_start_date=item.missing_dates[0] if item.missing_dates else None,
            requested_end_date=item.missing_dates[-1] if item.missing_dates else None,
            upserted_bars=0,
            estimated_requests=item.estimated_requests,
            notes=["Provider does not support this market/timeframe combination."],
        )

    if item.mode == "up_to_date":
        if progress_callback is not None:
            progress_callback(
                {
                    "status": "history_item_skipped",
                    "symbol": item.symbol,
                    "root_symbol": item.root_symbol,
                    "market": item.market,
                    "instrument_type": item.instrument_type,
                    "timeframe": item.timeframe,
                    "action": "noop",
                    "reason": "up_to_date",
                }
            )
        return SyncExecutionItem(
            symbol=item.symbol,
            root_symbol=item.root_symbol,
            market=item.market,
            instrument_type=item.instrument_type,
            timeframe=item.timeframe,
            mode=item.mode,
            action="noop",
            requested_start_date=None,
            requested_end_date=None,
            upserted_bars=0,
            estimated_requests=0,
            notes=["No missing trading_day detected in requested range."],
        )

    if item.mode == "repair" and not allow_repair:
        if progress_callback is not None:
            progress_callback(
                {
                    "status": "history_item_skipped",
                    "symbol": item.symbol,
                    "root_symbol": item.root_symbol,
                    "market": item.market,
                    "instrument_type": item.instrument_type,
                    "timeframe": item.timeframe,
                    "action": "skipped_repair",
                    "requested_start_date": item.missing_dates[0].isoformat(),
                    "requested_end_date": item.missing_dates[-1].isoformat(),
                }
            )
        return SyncExecutionItem(
            symbol=item.symbol,
            root_symbol=item.root_symbol,
            market=item.market,
            instrument_type=item.instrument_type,
            timeframe=item.timeframe,
            mode=item.mode,
            action="skipped_repair",
            requested_start_date=item.missing_dates[0],
            requested_end_date=item.missing_dates[-1],
            upserted_bars=0,
            estimated_requests=item.estimated_requests,
            notes=[
                "Repair execution is disabled. Run again with allow_repair once minute-level semantics are finalized."
            ],
        )

    if item.request_strategy == "per_symbol_per_day_chain":
        return _execute_per_day_chain_item(
            service=service,
            item=item,
            session_scope=session_scope,
            progress_callback=progress_callback,
        )

    requested_start = item.missing_dates[0]
    requested_end = item.missing_dates[-1]
    if progress_callback is not None:
        progress_callback(
            {
                "status": "history_item_started",
                "mode": "single_range",
                "symbol": item.symbol,
                "root_symbol": item.root_symbol,
                "market": item.market,
                "instrument_type": item.instrument_type,
                "timeframe": item.timeframe,
                "requested_start_date": requested_start.isoformat(),
                "requested_end_date": requested_end.isoformat(),
                "estimated_requests": item.estimated_requests,
            }
        )
    try:
        upserted = service.backfill(
            symbol=item.root_symbol,
            start_date=requested_start,
            end_date=requested_end,
            timeframe=item.timeframe,
            session_scope=session_scope,
        )
        action = "synced"
        notes: list[str] = []
    except Exception as exc:
        upserted = 0
        action = "failed"
        notes = [f"Sync failed: {exc}"]
    if progress_callback is not None:
        progress_callback(
            {
                "status": "history_item_completed",
                "mode": "single_range",
                "symbol": item.symbol,
                "root_symbol": item.root_symbol,
                "market": item.market,
                "instrument_type": item.instrument_type,
                "timeframe": item.timeframe,
                "requested_start_date": requested_start.isoformat(),
                "requested_end_date": requested_end.isoformat(),
                "upserted_bars": upserted,
                "action": action,
                "notes": notes,
            }
        )
    return SyncExecutionItem(
        symbol=item.symbol,
        root_symbol=item.root_symbol,
        market=item.market,
        instrument_type=item.instrument_type,
        timeframe=item.timeframe,
        mode=item.mode,
        action=action,
        requested_start_date=requested_start,
        requested_end_date=requested_end,
        upserted_bars=upserted,
        estimated_requests=item.estimated_requests,
        notes=notes,
    )


def _execute_per_day_chain_item(
    service: MaintenanceService,
    item: SyncPlanItem,
    session_scope: str,
    progress_callback: Callable[[dict], None] | None = None,
) -> SyncExecutionItem:
    upserted_total = 0
    failed_dates: list[date] = []

    for day in item.missing_dates:
        if progress_callback is not None:
            progress_callback(
                {
                    "status": "history_item_started",
                    "mode": "per_day_chain",
                    "symbol": item.symbol,
                    "root_symbol": item.root_symbol,
                    "market": item.market,
                    "instrument_type": item.instrument_type,
                    "timeframe": item.timeframe,
                    "requested_start_date": day.isoformat(),
                    "requested_end_date": day.isoformat(),
                    "estimated_requests": 1,
                }
            )
        try:
            upserted = service.backfill(
                symbol=item.root_symbol,
                start_date=day,
                end_date=day,
                timeframe=item.timeframe,
                session_scope=session_scope,
            )
            upserted_total += upserted
            if progress_callback is not None:
                progress_callback(
                    {
                        "status": "history_item_completed",
                        "mode": "per_day_chain",
                        "symbol": item.symbol,
                        "root_symbol": item.root_symbol,
                        "market": item.market,
                        "instrument_type": item.instrument_type,
                        "timeframe": item.timeframe,
                        "requested_start_date": day.isoformat(),
                        "requested_end_date": day.isoformat(),
                        "upserted_bars": upserted,
                        "action": "synced",
                    }
                )
        except Exception:
            failed_dates.append(day)
            if progress_callback is not None:
                progress_callback(
                    {
                        "status": "history_item_completed",
                        "mode": "per_day_chain",
                        "symbol": item.symbol,
                        "root_symbol": item.root_symbol,
                        "market": item.market,
                        "instrument_type": item.instrument_type,
                        "timeframe": item.timeframe,
                        "requested_start_date": day.isoformat(),
                        "requested_end_date": day.isoformat(),
                        "upserted_bars": 0,
                        "action": "failed",
                    }
                )

    notes: list[str] = []
    action = "synced"
    if failed_dates:
        action = "partial_failed" if upserted_total > 0 else "failed"
        failed_preview = ", ".join(day.isoformat() for day in failed_dates[:5])
        notes.append(
            f"Failed dates={len(failed_dates)}. Sample: {failed_preview}"
            + (" ..." if len(failed_dates) > 5 else "")
        )

    return SyncExecutionItem(
        symbol=item.symbol,
        root_symbol=item.root_symbol,
        market=item.market,
        instrument_type=item.instrument_type,
        timeframe=item.timeframe,
        mode=item.mode,
        action=action,
        requested_start_date=item.missing_dates[0],
        requested_end_date=item.missing_dates[-1],
        upserted_bars=upserted_total,
        estimated_requests=item.estimated_requests,
        notes=notes,
    )
