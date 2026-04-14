from __future__ import annotations

from qt_platform.domain import Side, Signal
from qt_platform.strategies.base import BaseStrategy, StrategyContext


class ForceImbalanceStrategy(BaseStrategy):
    def __init__(
        self,
        min_force_score: float = 500.0,
        min_tick_bias_ratio: float = 0.1,
        allow_short: bool = True,
    ) -> None:
        self.min_force_score = min_force_score
        self.min_tick_bias_ratio = min_tick_bias_ratio
        self.allow_short = allow_short
        self._last_state: str | None = None

    def on_bar(self, context: StrategyContext) -> list[Signal]:
        features = context.minute_features
        if features is None or features.tick_total <= 0:
            return []

        state = self._classify(features.force_score, features.tick_bias_ratio)
        if state == "flat":
            self._last_state = state
            return []

        if state == self._last_state:
            return []

        self._last_state = state
        side = Side.BUY if state == "long" else Side.SELL
        return [
            Signal(
                ts=context.bar.ts,
                side=side,
                reason=(
                    f"force_imbalance:"
                    f"force_score={features.force_score:.2f},"
                    f"tick_bias_ratio={features.tick_bias_ratio:.4f}"
                ),
            )
        ]

    def _classify(self, force_score: float, tick_bias_ratio: float) -> str:
        if force_score >= self.min_force_score and tick_bias_ratio >= self.min_tick_bias_ratio:
            return "long"
        if self.allow_short and force_score <= -self.min_force_score and tick_bias_ratio <= -self.min_tick_bias_ratio:
            return "short"
        return "flat"
