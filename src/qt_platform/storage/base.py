from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Iterable

from qt_platform.domain import Bar, CanonicalTick, LiveRunMetadata
from qt_platform.features import MinuteForceFeatures


class BarRepository(ABC):
    @abstractmethod
    def upsert_bars(self, timeframe: str, bars: Iterable[Bar]) -> int:
        raise NotImplementedError

    @abstractmethod
    def list_bars(self, timeframe: str, symbol: str, start: datetime, end: datetime) -> list[Bar]:
        raise NotImplementedError

    @abstractmethod
    def latest_bar_ts(self, timeframe: str, symbol: str) -> datetime | None:
        raise NotImplementedError

    @abstractmethod
    def list_trading_days(
        self,
        timeframe: str,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> list[date]:
        raise NotImplementedError

    @abstractmethod
    def update_sync_cursor(
        self,
        source: str,
        symbol: str,
        timeframe: str,
        session_scope: str,
        cursor_ts: datetime | None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_sync_cursor(
        self,
        source: str,
        symbol: str,
        timeframe: str,
        session_scope: str,
    ) -> datetime | None:
        raise NotImplementedError

    @abstractmethod
    def append_ticks(self, ticks: Iterable[CanonicalTick]) -> int:
        raise NotImplementedError

    @abstractmethod
    def list_ticks(self, symbol: str, start: datetime, end: datetime) -> list[CanonicalTick]:
        raise NotImplementedError

    @abstractmethod
    def upsert_minute_force_features(self, features: Iterable[MinuteForceFeatures]) -> int:
        raise NotImplementedError

    @abstractmethod
    def list_minute_force_features(
        self,
        symbol: str | None,
        start: datetime,
        end: datetime,
        run_id: str | None = None,
        symbols: list[str] | None = None,
        instrument_keys: list[str] | None = None,
        contract_month: str | None = None,
        strike_price: float | None = None,
        call_put: str | None = None,
    ) -> list[MinuteForceFeatures]:
        raise NotImplementedError

    @abstractmethod
    def create_live_run(self, metadata: LiveRunMetadata) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_live_run(self, run_id: str) -> LiveRunMetadata | None:
        raise NotImplementedError
