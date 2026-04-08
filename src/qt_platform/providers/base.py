from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from qt_platform.domain import Bar


class BaseProvider(ABC):
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

