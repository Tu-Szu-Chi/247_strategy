from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Iterable

from qt_platform.domain import Bar


class BarRepository(ABC):
    @abstractmethod
    def upsert_bars(self, bars: Iterable[Bar]) -> int:
        raise NotImplementedError

    @abstractmethod
    def list_bars(self, symbol: str, start: datetime, end: datetime) -> list[Bar]:
        raise NotImplementedError

    @abstractmethod
    def latest_bar_ts(self, symbol: str) -> datetime | None:
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

