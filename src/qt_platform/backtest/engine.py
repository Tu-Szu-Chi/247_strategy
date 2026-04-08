from __future__ import annotations

from dataclasses import dataclass

from qt_platform.domain import BacktestResult, Bar, Fill, Side, Signal, Trade
from qt_platform.strategies.base import BaseStrategy


@dataclass(frozen=True)
class BacktestConfig:
    starting_cash: float = 1_000_000.0
    trade_size: int = 1


def run_backtest(bars: list[Bar], strategy: BaseStrategy, config: BacktestConfig) -> BacktestResult:
    cash = config.starting_cash
    pending_signals: list[Signal] = []
    fills: list[Fill] = []
    trades: list[Trade] = []
    equity_curve: list[tuple] = []
    open_fill: Fill | None = None

    for bar in bars:
        if pending_signals:
            signal = pending_signals.pop(0)
            fill = Fill(ts=bar.ts, side=signal.side, price=bar.open, size=signal.size, reason=signal.reason)
            fills.append(fill)

            if open_fill is None:
                open_fill = fill
            else:
                if open_fill.side != fill.side:
                    trade = Trade(
                        entry_ts=open_fill.ts,
                        exit_ts=fill.ts,
                        side=open_fill.side,
                        entry_price=open_fill.price,
                        exit_price=fill.price,
                        size=min(open_fill.size, fill.size),
                    )
                    trades.append(trade)
                    cash += trade.pnl
                    open_fill = None
                else:
                    open_fill = fill

        pending_signals.extend(strategy.on_bar(bar))

        marked_equity = cash
        if open_fill is not None:
            direction = 1 if open_fill.side == Side.BUY else -1
            marked_equity += (bar.close - open_fill.price) * direction * open_fill.size
        equity_curve.append((bar.ts, marked_equity))

    ending_cash = equity_curve[-1][1] if equity_curve else cash
    metrics = {
        "total_trades": len(trades),
        "net_pnl": ending_cash - config.starting_cash,
        "win_rate": _win_rate(trades),
    }
    return BacktestResult(
        starting_cash=config.starting_cash,
        ending_cash=ending_cash,
        equity_curve=equity_curve,
        fills=fills,
        trades=trades,
        metrics=metrics,
    )


def _win_rate(trades: list[Trade]) -> float:
    if not trades:
        return 0.0
    wins = sum(1 for trade in trades if trade.pnl > 0)
    return wins / len(trades)

