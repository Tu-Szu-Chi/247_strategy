from __future__ import annotations

from datetime import date, datetime, timedelta

from qt_platform.domain import Gap
from qt_platform.providers.base import BaseProvider
from qt_platform.storage.base import BarRepository


class MaintenanceService:
    def __init__(self, provider: BaseProvider, store: BarRepository) -> None:
        self.provider = provider
        self.store = store

    def scan_gaps(self, symbol: str, start: datetime, end: datetime, expected_step: timedelta) -> list[Gap]:
        bars = self.store.list_bars(timeframe="1m", symbol=symbol, start=start, end=end)
        if not bars:
            return [Gap(start=start, end=end)]

        gaps: list[Gap] = []
        expected = start
        for bar in bars:
            if bar.ts > expected:
                gaps.append(Gap(start=expected, end=bar.ts - expected_step))
            next_expected = bar.ts + expected_step
            if next_expected > expected:
                expected = next_expected

        if expected <= end:
            gaps.append(Gap(start=expected, end=end))
        return gaps

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
