from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from qt_platform.domain import Bar, Fill, Signal
from qt_platform.features import MinuteForceFeatures


@dataclass(frozen=True)
class StrategyContext:
    bar: Bar
    minute_features: MinuteForceFeatures | None = None
    open_fill: Fill | None = None
    position_size: int = 0
    average_entry_price: float | None = None
    bar_index: int = 0
    total_bars: int = 0
    extras: dict[str, Any] = field(default_factory=dict)


class BaseStrategy(ABC):
    @abstractmethod
    def on_bar(self, context: StrategyContext) -> list[Signal]:
        raise NotImplementedError
