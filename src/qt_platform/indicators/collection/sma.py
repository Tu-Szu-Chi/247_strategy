from __future__ import annotations

from qt_platform.indicators.base import Indicator, IndicatorValue, StreamType
from qt_platform.indicators.registry import register_indicator


@register_indicator
class SmaIndicator(Indicator):
    """
    Simple Moving Average Indicator.
    Demonstrates the use of lookback and historical data.
    """
    
    def __init__(self, window: int = 20):
        self._window = window
    
    @property
    def name(self) -> str:
        return f"sma_{self._window}"

    @property
    def input_slots(self) -> dict[str, StreamType]:
        return {"src": StreamType.BAR}

    @property
    def lookback(self) -> int:
        return self._window

    def update(self, context) -> IndicatorValue:
        history = context.get_history("src", n=self._window)
        if len(history) < self._window:
            return IndicatorValue(value=None, timestamp=context.ts, metadata={"ready": False})
            
        closes = [getattr(bar, "close", 0.0) for bar in history]
        sma = sum(closes) / len(closes)
        
        return IndicatorValue(
            value=sma,
            timestamp=context.ts,
            metadata={"window": self._window, "ready": True}
        )
