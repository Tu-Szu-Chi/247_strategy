from __future__ import annotations

from datetime import date, datetime, timedelta

from qt_platform.domain import Gap
from qt_platform.providers.base import BaseProvider
from qt_platform.trading_calendar import iter_expected_bar_timestamps
from qt_platform.storage.base import BarRepository


class MaintenanceService:
    def __init__(self, provider: BaseProvider, store: BarRepository) -> None:
        self.provider = provider
        self.store = store

    def scan_gaps(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        expected_step: timedelta,
        session_scope: str = "day_and_night",
    ) -> list[Gap]:
        bars = self.store.list_bars(timeframe="1m", symbol=symbol, start=start, end=end)
        expected = iter_expected_bar_timestamps(start, end, expected_step, session_scope)
        actual = {bar.ts for bar in bars}
        missing = [ts for ts in expected if ts not in actual]
        return _compress_missing_timestamps(missing, expected_step)

    def catch_up(
        self,
        symbol: str,
        end_date: date,
        timeframe: str,
        session_scope: str,
    ) -> int:
        latest = self.store.latest_bar_ts(timeframe, symbol)
        if latest is None:
            raise ValueError("No existing data. Use backfill first.")
        start_date = latest.date()
        return self.backfill(symbol, start_date, end_date, timeframe, session_scope)

    def backfill(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        timeframe: str,
        session_scope: str,
    ) -> int:
        bars = self.provider.fetch_history(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            timeframe=timeframe,
            session_scope=session_scope,
        )
        inserted = self.store.upsert_bars(timeframe, bars)
        cursor_ts = bars[-1].ts if bars else None
        self.store.update_sync_cursor(
            source="finmind",
            symbol=symbol,
            timeframe=timeframe,
            session_scope=session_scope,
            cursor_ts=cursor_ts,
        )
        return inserted


def _compress_missing_timestamps(missing: list[datetime], step: timedelta) -> list[Gap]:
    if not missing:
        return []

    gaps: list[Gap] = []
    gap_start = missing[0]
    previous = missing[0]

    for ts in missing[1:]:
        if ts - previous != step:
            gaps.append(Gap(start=gap_start, end=previous))
            gap_start = ts
        previous = ts

    gaps.append(Gap(start=gap_start, end=previous))
    return gaps
