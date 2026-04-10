from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from qt_platform.domain import Bar


class BaseProvider(ABC):
    @abstractmethod
    def supports_history(
        self,
        market: str,
        instrument_type: str,
        symbol: str,
        timeframe: str,
    ) -> bool:
        raise NotImplementedError

    @abstractmethod
    def fetch_history(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        timeframe: str,
        session_scope: str,
    ) -> list[Bar]:
        raise NotImplementedError

    def fetch_history_batch(
        self,
        market: str,
        symbols: list[str],
        start_date: date,
        end_date: date,
        timeframe: str,
        session_scope: str,
    ) -> dict[str, list[Bar]]:
        batches: dict[str, list[Bar]] = {}
        for symbol in symbols:
            if not self.supports_history(market=market, instrument_type="unknown", symbol=symbol, timeframe=timeframe):
                batches[symbol] = []
                continue
            batches[symbol] = self.fetch_history(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                timeframe=timeframe,
                session_scope=session_scope,
            )
        return batches
