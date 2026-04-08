from __future__ import annotations

from collections import deque

from qt_platform.domain import Bar, Side, Signal
from qt_platform.strategies.base import BaseStrategy


class SmaCrossStrategy(BaseStrategy):
    def __init__(self, fast_window: int = 5, slow_window: int = 20) -> None:
        if fast_window >= slow_window:
            raise ValueError("fast_window must be smaller than slow_window")
        self.fast_window = fast_window
        self.slow_window = slow_window
        self._closes: deque[float] = deque(maxlen=slow_window)
        self._last_state: str | None = None

    def on_bar(self, bar: Bar) -> list[Signal]:
        self._closes.append(bar.close)
        if len(self._closes) < self.slow_window:
            return []

        closes = list(self._closes)
        fast = sum(closes[-self.fast_window:]) / self.fast_window
        slow = sum(closes) / self.slow_window
        state = "above" if fast > slow else "below"

        if self._last_state is None:
            self._last_state = state
            return []

        if state == self._last_state:
            return []

        self._last_state = state
        side = Side.BUY if state == "above" else Side.SELL
        return [Signal(ts=bar.ts, side=side, reason=f"sma_cross_{state}")]

