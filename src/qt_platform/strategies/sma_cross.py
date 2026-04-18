from __future__ import annotations

from collections import deque

from qt_platform.strategies.base import (
    BarCloseEvent,
    BaseIndicator,
    BaseSignalLogic,
    BaseStrategyDefinition,
    FixedSizeExecutionPolicy,
    IndicatorValue,
    SignalAction,
    SignalDecisionContext,
    SignalIntent,
    StrategyUniverse,
)


class SmaIndicator(BaseIndicator):
    def __init__(self, window: int) -> None:
        if window <= 0:
            raise ValueError("window must be positive")
        self.window = window
        self._closes: deque[float] = deque(maxlen=window)

    def on_bar(self, event: BarCloseEvent) -> None:
        self._closes.append(event.bar.close)

    def snapshot(self) -> IndicatorValue:
        if len(self._closes) < self.window:
            return IndicatorValue(value=None, ready=False, metadata={"window": self.window})
        return IndicatorValue(
            value=sum(self._closes) / self.window,
            ready=True,
            metadata={"window": self.window},
        )


class SmaCrossSignalLogic(BaseSignalLogic):
    def __init__(self) -> None:
        self._last_state: str | None = None

    def dependencies(self) -> tuple[str, ...]:
        return ("fast_sma", "slow_sma")

    def evaluate(
        self,
        context: SignalDecisionContext,
        indicator_values: dict[str, IndicatorValue],
    ) -> list[SignalIntent]:
        fast = indicator_values["fast_sma"]
        slow = indicator_values["slow_sma"]
        if not fast.ready or not slow.ready:
            return []

        state = "above" if fast.value > slow.value else "below"
        if self._last_state is None:
            self._last_state = state
            return []
        if state == self._last_state:
            return []

        self._last_state = state
        return [
            SignalIntent(
                ts=context.event.bar.ts,
                symbol=context.event.bar.symbol,
                action=SignalAction.BUY if state == "above" else SignalAction.SELL,
                strength=abs(float(fast.value) - float(slow.value)),
                reason=f"sma_cross_{state}",
                metadata={"fast_sma": fast.value, "slow_sma": slow.value},
            )
        ]


class SmaCrossStrategy(BaseStrategyDefinition):
    def __init__(self, fast_window: int = 5, slow_window: int = 20) -> None:
        if fast_window >= slow_window:
            raise ValueError("fast_window must be smaller than slow_window")
        self.fast_window = fast_window
        self.slow_window = slow_window
        self._indicators = {
            "fast_sma": SmaIndicator(window=fast_window),
            "slow_sma": SmaIndicator(window=slow_window),
        }
        self._signal_logic = SmaCrossSignalLogic()
        self._execution_policy = FixedSizeExecutionPolicy(trade_size=1, max_position=1)

    def universe(self) -> StrategyUniverse:
        return StrategyUniverse(primary_symbol="")

    def indicators(self) -> dict[str, BaseIndicator]:
        return self._indicators

    def signal_logic(self) -> BaseSignalLogic:
        return self._signal_logic

    def execution_policy(self) -> FixedSizeExecutionPolicy:
        return self._execution_policy
