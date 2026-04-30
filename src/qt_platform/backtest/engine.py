from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from qt_platform.domain import BacktestResult, Bar, Fill, Side, Signal, Trade
from qt_platform.features import compute_minute_force_features
from qt_platform.strategies.base import (
    BarCloseEvent,
    BaseStrategy,
    BaseStrategyDefinition,
    PortfolioState,
    StrategyContext,
    StrategyRuntime,
)


@dataclass(frozen=True)
class BacktestConfig:
    starting_cash: float = 1_000_000.0
    trade_size: int = 1


def run_backtest(
    bars: list[Bar],
    strategy: BaseStrategy | BaseStrategyDefinition,
    config: BacktestConfig,
    context_extras_by_ts: dict[Any, dict[str, Any]] | None = None,
    indicator_series: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> BacktestResult:
    cash = config.starting_cash
    pending_signals: list[Signal] = []
    fills: list[Fill] = []
    trades: list[Trade] = []
    equity_curve: list[tuple] = []
    open_fills: list[Fill] = []
    runtime = StrategyRuntime(strategy) if isinstance(strategy, BaseStrategyDefinition) else None
    indicator_extras_by_ts = indicator_series_to_context_extras(indicator_series or {})

    for index, bar in enumerate(bars):
        if pending_signals:
            still_pending: list[Signal] = []
            for signal in pending_signals:
                if signal.execution_mode != "next_open":
                    still_pending.append(signal)
                    continue
                fill_price = signal.target_price if signal.target_price is not None else bar.open
                fill = Fill(
                    ts=bar.ts,
                    side=signal.side,
                    price=fill_price,
                    size=signal.size,
                    reason=signal.reason,
                    metadata=dict(signal.metadata),
                )
                fills.append(fill)
                cash = _apply_fill(fill, open_fills, trades, cash)
            pending_signals = still_pending

        position_size = _position_size(open_fills)
        average_entry_price = _average_entry_price(open_fills)
        extras = {
            **indicator_extras_by_ts.get(bar.ts, {}),
            **(context_extras_by_ts or {}).get(bar.ts, {}),
        }
        context = StrategyContext(
            bar=bar,
            minute_features=compute_minute_force_features(bar),
            open_fill=open_fills[-1] if open_fills else None,
            position_size=position_size,
            average_entry_price=average_entry_price,
            bar_index=index,
            total_bars=len(bars),
            extras=extras,
        )
        if runtime is not None:
            emitted_signals = runtime.on_bar(
                BarCloseEvent(
                    bar=bar,
                    minute_features=context.minute_features,
                    bar_index=index,
                    total_bars=len(bars),
                    extras=extras,
                ),
                PortfolioState(
                    cash=cash,
                    position_size=position_size,
                    average_entry_price=average_entry_price,
                ),
            )
        else:
            emitted_signals = strategy.on_bar(context)
        immediate_signals = [signal for signal in emitted_signals if signal.execution_mode == "same_bar"]
        pending_signals.extend(signal for signal in emitted_signals if signal.execution_mode != "same_bar")

        for signal in immediate_signals:
            fill_price = signal.target_price if signal.target_price is not None else bar.close
            fill = Fill(
                ts=bar.ts,
                side=signal.side,
                price=fill_price,
                size=signal.size,
                reason=signal.reason,
                metadata=dict(signal.metadata),
            )
            fills.append(fill)
            cash = _apply_fill(fill, open_fills, trades, cash)

        marked_equity = cash
        for open_fill in open_fills:
            direction = 1 if open_fill.side == Side.BUY else -1
            marked_equity += (bar.close - open_fill.price) * direction * open_fill.size
        equity_curve.append((bar.ts, marked_equity))

    ending_cash = equity_curve[-1][1] if equity_curve else cash
    metrics = {
        "total_trades": len(trades),
        "net_pnl": ending_cash - config.starting_cash,
        "win_rate": _win_rate(trades),
        "ending_position_size": _position_size(open_fills),
    }
    return BacktestResult(
        starting_cash=config.starting_cash,
        ending_cash=ending_cash,
        equity_curve=equity_curve,
        fills=fills,
        trades=trades,
        metrics=metrics,
    )


def indicator_series_to_context_extras(
    series: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[datetime, dict[str, Any]]:
    extras_by_ts: dict[datetime, dict[str, Any]] = {}
    for name, points in series.items():
        for point in points:
            raw_time = point.get("time")
            if raw_time is None:
                continue
            ts = raw_time if isinstance(raw_time, datetime) else datetime.fromisoformat(str(raw_time))
            extras_by_ts.setdefault(ts, {})[name] = point.get("value")
    return extras_by_ts


def _apply_fill(fill: Fill, open_fills: list[Fill], trades: list[Trade], cash: float) -> float:
    if not open_fills:
        open_fills.append(fill)
        return cash

    current_side = open_fills[0].side
    if current_side == fill.side:
        open_fills.append(fill)
        return cash

    remaining = fill.size
    while remaining > 0 and open_fills:
        entry_fill = open_fills[0]
        matched = min(entry_fill.size, remaining)
        trade = Trade(
            entry_ts=entry_fill.ts,
            exit_ts=fill.ts,
            side=entry_fill.side,
            entry_price=entry_fill.price,
            exit_price=fill.price,
            size=matched,
        )
        trades.append(trade)
        cash += trade.pnl

        remaining -= matched
        if entry_fill.size == matched:
            open_fills.pop(0)
        else:
            open_fills[0] = Fill(
                ts=entry_fill.ts,
                side=entry_fill.side,
                price=entry_fill.price,
                size=entry_fill.size - matched,
                reason=entry_fill.reason,
                metadata=dict(entry_fill.metadata),
            )

    if remaining > 0:
        open_fills.append(
            Fill(
                ts=fill.ts,
                side=fill.side,
                price=fill.price,
                size=remaining,
                reason=fill.reason,
                metadata=dict(fill.metadata),
            )
        )
    return cash


def _position_size(open_fills: list[Fill]) -> int:
    if not open_fills:
        return 0
    direction = 1 if open_fills[0].side == Side.BUY else -1
    return direction * sum(fill.size for fill in open_fills)


def _average_entry_price(open_fills: list[Fill]) -> float | None:
    if not open_fills:
        return None
    total_size = sum(fill.size for fill in open_fills)
    if total_size <= 0:
        return None
    return sum(fill.price * fill.size for fill in open_fills) / total_size


def _win_rate(trades: list[Trade]) -> float:
    if not trades:
        return 0.0
    wins = sum(1 for trade in trades if trade.pnl > 0)
    return wins / len(trades)
