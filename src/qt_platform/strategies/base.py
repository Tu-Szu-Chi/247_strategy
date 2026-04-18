from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from qt_platform.domain import Bar, CanonicalTick, Fill, Side, Signal
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


@dataclass(frozen=True)
class StrategyUniverse:
    primary_symbol: str
    reference_symbols: tuple[str, ...] = ()
    streams: tuple[str, ...] = ("bars_1m",)


@dataclass(frozen=True)
class PortfolioState:
    cash: float
    position_size: int = 0
    average_entry_price: float | None = None


@dataclass(frozen=True)
class TickEvent:
    tick: CanonicalTick


@dataclass(frozen=True)
class BarCloseEvent:
    bar: Bar
    minute_features: MinuteForceFeatures | None = None
    bar_index: int = 0
    total_bars: int = 0
    extras: dict[str, Any] = field(default_factory=dict)


class SignalAction(str, Enum):
    BUY = "buy"
    SELL = "sell"
    FLAT = "flat"
    HOLD = "hold"


@dataclass(frozen=True)
class IndicatorValue:
    value: Any
    ready: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseIndicator(ABC):
    def required_inputs(self) -> tuple[str, ...]:
        return ()

    def on_tick(self, event: TickEvent) -> None:
        return None

    def on_bar(self, event: BarCloseEvent) -> None:
        return None

    @abstractmethod
    def snapshot(self) -> IndicatorValue:
        raise NotImplementedError


@dataclass(frozen=True)
class SignalIntent:
    ts: Any
    symbol: str
    action: SignalAction
    strength: float = 1.0
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SignalDecisionContext:
    event: BarCloseEvent
    portfolio: PortfolioState
    universe: StrategyUniverse


class BaseSignalLogic(ABC):
    def dependencies(self) -> tuple[str, ...]:
        return ()

    @abstractmethod
    def evaluate(
        self,
        context: SignalDecisionContext,
        indicator_values: dict[str, IndicatorValue],
    ) -> list[SignalIntent]:
        raise NotImplementedError


@dataclass(frozen=True)
class OrderRequest:
    ts: Any
    symbol: str
    side: Side
    size: int
    reason: str = ""
    execution_mode: str = "next_open"
    target_price: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionDecisionContext:
    event: BarCloseEvent
    portfolio: PortfolioState
    universe: StrategyUniverse


class BaseExecutionPolicy(ABC):
    @abstractmethod
    def decide(
        self,
        intents: list[SignalIntent],
        context: ExecutionDecisionContext,
    ) -> list[OrderRequest]:
        raise NotImplementedError


class BaseStrategyDefinition(ABC):
    def universe(self) -> StrategyUniverse:
        return StrategyUniverse(primary_symbol="")

    @abstractmethod
    def indicators(self) -> dict[str, BaseIndicator]:
        raise NotImplementedError

    @abstractmethod
    def signal_logic(self) -> BaseSignalLogic:
        raise NotImplementedError

    @abstractmethod
    def execution_policy(self) -> BaseExecutionPolicy:
        raise NotImplementedError


class FixedSizeExecutionPolicy(BaseExecutionPolicy):
    def __init__(self, trade_size: int = 1, max_position: int = 1) -> None:
        if trade_size <= 0:
            raise ValueError("trade_size must be positive")
        if max_position <= 0:
            raise ValueError("max_position must be positive")
        self.trade_size = trade_size
        self.max_position = max_position

    def decide(
        self,
        intents: list[SignalIntent],
        context: ExecutionDecisionContext,
    ) -> list[OrderRequest]:
        orders: list[OrderRequest] = []
        position = context.portfolio.position_size
        for intent in intents:
            if intent.action not in {SignalAction.BUY, SignalAction.SELL}:
                continue
            side = Side.BUY if intent.action == SignalAction.BUY else Side.SELL
            if side == Side.BUY:
                size = self._buy_size(position)
                if size <= 0:
                    continue
                position += size
            else:
                size = self._sell_size(position)
                if size <= 0:
                    continue
                position -= size
            orders.append(
                OrderRequest(
                    ts=intent.ts,
                    symbol=intent.symbol,
                    side=side,
                    size=size,
                    reason=intent.reason,
                )
            )
        return orders

    def _buy_size(self, position: int) -> int:
        if position < 0:
            return min(self.trade_size, abs(position))
        if position >= self.max_position:
            return 0
        return min(self.trade_size, self.max_position - position)

    def _sell_size(self, position: int) -> int:
        if position > 0:
            return min(self.trade_size, position)
        if abs(position) >= self.max_position:
            return 0
        return min(self.trade_size, self.max_position - abs(position))


class StrategyRuntime:
    def __init__(self, definition: BaseStrategyDefinition) -> None:
        self.definition = definition
        self._indicators = definition.indicators()
        self._signal_logic = definition.signal_logic()
        self._execution_policy = definition.execution_policy()
        self._universe = definition.universe()

    def on_tick(self, tick: CanonicalTick) -> None:
        event = TickEvent(tick=tick)
        for indicator in self._indicators.values():
            indicator.on_tick(event)

    def on_bar(self, event: BarCloseEvent, portfolio: PortfolioState) -> list[Signal]:
        for indicator in self._indicators.values():
            indicator.on_bar(event)
        indicator_values = {name: indicator.snapshot() for name, indicator in self._indicators.items()}
        intents = self._signal_logic.evaluate(
            SignalDecisionContext(event=event, portfolio=portfolio, universe=self._universe),
            indicator_values,
        )
        orders = self._execution_policy.decide(
            intents,
            ExecutionDecisionContext(event=event, portfolio=portfolio, universe=self._universe),
        )
        return [
            Signal(
                ts=order.ts,
                side=order.side,
                size=order.size,
                reason=order.reason,
                execution_mode=order.execution_mode,
                target_price=order.target_price,
            )
            for order in orders
        ]
