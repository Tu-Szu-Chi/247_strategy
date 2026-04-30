from __future__ import annotations

from typing import Any

from qt_platform.option_power.indicator_backend import INDICATOR_SERIES_NAMES
from qt_platform.strategies.base import (
    BaseIndicator,
    BaseSignalLogic,
    BaseStrategyDefinition,
    FixedSizeExecutionPolicy,
    SignalAction,
    SignalDecisionContext,
    SignalIntent,
    StrategyUniverse,
)


class OptionPowerSignalLogic(BaseSignalLogic):
    def __init__(
        self,
        *,
        signal_field: str = "signal_state",
        bias_field: str = "bias_signal",
        require_bias_alignment: bool = True,
        exit_on_neutral: bool = True,
    ) -> None:
        self.signal_field = signal_field
        self.bias_field = bias_field
        self.require_bias_alignment = require_bias_alignment
        self.exit_on_neutral = exit_on_neutral

    def evaluate(
        self,
        context: SignalDecisionContext,
        indicator_values: dict[str, object],
    ) -> list[SignalIntent]:
        target_direction = _direction(context.event.extras.get(self.signal_field))
        bias_direction = _direction(context.event.extras.get(self.bias_field))
        if self.require_bias_alignment and target_direction != 0 and bias_direction != target_direction:
            target_direction = 0

        current_direction = _position_direction(context.portfolio.position_size)
        if target_direction == 0:
            if not self.exit_on_neutral or current_direction == 0:
                return []
            action = SignalAction.SELL if current_direction > 0 else SignalAction.BUY
            return [
                SignalIntent(
                    ts=context.event.bar.ts,
                    symbol=context.event.bar.symbol,
                    action=action,
                    reason="option_power_signal_flat",
                    metadata=_metadata(context.event.extras, target_direction, bias_direction),
                )
            ]

        if current_direction == target_direction:
            return []

        return [
            SignalIntent(
                ts=context.event.bar.ts,
                symbol=context.event.bar.symbol,
                action=SignalAction.BUY if target_direction > 0 else SignalAction.SELL,
                strength=abs(float(context.event.extras.get(self.signal_field) or 0)),
                reason="option_power_signal_long" if target_direction > 0 else "option_power_signal_short",
                metadata=_metadata(context.event.extras, target_direction, bias_direction),
            )
        ]


class OptionPowerSignalStrategy(BaseStrategyDefinition):
    def __init__(
        self,
        *,
        trade_size: int = 1,
        max_position: int = 1,
        require_bias_alignment: bool = True,
        exit_on_neutral: bool = True,
    ) -> None:
        self.trade_size = trade_size
        self.max_position = max_position
        self._signal_logic = OptionPowerSignalLogic(
            require_bias_alignment=require_bias_alignment,
            exit_on_neutral=exit_on_neutral,
        )
        self._execution_policy = FixedSizeExecutionPolicy(
            trade_size=trade_size,
            max_position=max_position,
        )

    def universe(self) -> StrategyUniverse:
        return StrategyUniverse(primary_symbol="")

    def indicators(self) -> dict[str, BaseIndicator]:
        return {}

    def signal_logic(self) -> BaseSignalLogic:
        return self._signal_logic

    def execution_policy(self) -> FixedSizeExecutionPolicy:
        return self._execution_policy


def _direction(value: object) -> int:
    try:
        numeric = float(value or 0)
    except (TypeError, ValueError):
        return 0
    if numeric > 0:
        return 1
    if numeric < 0:
        return -1
    return 0


def _position_direction(position_size: int) -> int:
    if position_size > 0:
        return 1
    if position_size < 0:
        return -1
    return 0


def _metadata(extras: dict[str, Any], target_direction: int, bias_direction: int) -> dict[str, Any]:
    indicator_values = {
        name: extras[name]
        for name in INDICATOR_SERIES_NAMES
        if name in extras and extras[name] is not None
    }
    return {
        "signal_state": extras.get("signal_state"),
        "bias_signal": extras.get("bias_signal"),
        "target_direction": target_direction,
        "bias_direction": bias_direction,
        "indicator_values": indicator_values,
    }
