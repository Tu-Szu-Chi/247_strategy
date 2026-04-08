from __future__ import annotations

from abc import ABC, abstractmethod

from qt_platform.domain import Bar, Signal


class BaseStrategy(ABC):
    @abstractmethod
    def on_bar(self, bar: Bar) -> list[Signal]:
        raise NotImplementedError

