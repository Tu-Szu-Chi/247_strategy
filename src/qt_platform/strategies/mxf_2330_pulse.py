from __future__ import annotations

from datetime import time

from qt_platform.domain import Side, Signal
from qt_platform.strategies.base import BaseStrategy, StrategyContext


class Mxf2330PulseStrategy(BaseStrategy):
    def __init__(
        self,
        growth_threshold: float = 0.3,
        max_position: int = 2,
        stop_loss_points: float = 100.0,
        force_exit_time: str = "13:30",
    ) -> None:
        self.growth_threshold = growth_threshold
        self.max_position = max_position
        self.stop_loss_points = stop_loss_points
        self.force_exit_time = time.fromisoformat(force_exit_time)

    def on_bar(self, context: StrategyContext) -> list[Signal]:
        bar = context.bar
        if bar.session != "day":
            return []

        if context.position_size > 0 and bar.ts.time() >= self.force_exit_time:
            return [
                Signal(
                    ts=bar.ts,
                    side=Side.SELL,
                    size=context.position_size,
                    reason="time_exit_1330",
                    execution_mode="same_bar",
                    target_price=bar.close,
                )
            ]

        if context.position_size > 0 and context.average_entry_price is not None:
            stop_price = context.average_entry_price - self.stop_loss_points
            if bar.low <= stop_price:
                return [
                    Signal(
                        ts=bar.ts,
                        side=Side.SELL,
                        size=context.position_size,
                        reason=f"stop_loss_{self.stop_loss_points:.0f}",
                        execution_mode="same_bar",
                        target_price=stop_price,
                    )
                ]

        growth = context.extras.get("ref_growth_5m")
        current_ratio = context.extras.get("ref_tick_bias_ratio_5m")
        if growth is None or current_ratio is None:
            return []
        if current_ratio <= 0 or growth < self.growth_threshold:
            return []
        if context.position_size >= self.max_position:
            return []

        return [
            Signal(
                ts=bar.ts,
                side=Side.BUY,
                size=1,
                reason=(
                    f"mxf_2330_pulse:"
                    f"growth={growth:.4f},"
                    f"ratio={current_ratio:.4f}"
                ),
            )
        ]
