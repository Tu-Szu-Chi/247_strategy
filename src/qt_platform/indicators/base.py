from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class StreamType(Enum):
    BAR = "bar"
    TICK = "tick"
    ORDER_BOOK = "order_book"
    PRICE_ONLY = "price_only"


@dataclass(frozen=True)
class IndicatorValue:
    value: Any
    timestamp: Any
    metadata: Mapping[str, Any] = field(default_factory=dict)


class Indicator(ABC):
    """
    Base class for all indicators. 
    Indicators are purely algorithmic and should not maintain global state.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this indicator class."""
        pass

    @property
    def input_slots(self) -> dict[str, StreamType]:
        """Define the logical input slots required by this indicator."""
        return {}

    @property
    def dependencies(self) -> list[str]:
        """Names of other indicators this indicator depends on."""
        return []

    @property
    def lookback(self) -> int:
        """Number of historical units (bars/ticks) required for calculation."""
        return 1

    @abstractmethod
    def update(self, context: Any) -> IndicatorValue:
        """
        Perform calculation based on the provided context.
        The context is typically an instance of IndicatorContext.
        """
        pass
