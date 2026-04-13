from __future__ import annotations

from dataclasses import asdict, dataclass

from qt_platform.domain import Bar


@dataclass(frozen=True)
class MinuteForceFeatures:
    ts: str
    symbol: str
    instrument_key: str | None
    contract_month: str
    strike_price: float | None
    call_put: str | None
    run_id: str | None
    close: float
    volume: float
    up_ticks: float | None
    down_ticks: float | None
    tick_total: float
    net_tick_count: float
    tick_bias_ratio: float
    volume_per_tick: float | None
    force_score: float

    def to_dict(self) -> dict:
        return asdict(self)


def compute_minute_force_features(bar: Bar, run_id: str | None = None) -> MinuteForceFeatures:
    up_ticks = bar.up_ticks if bar.up_ticks is not None else 0.0
    down_ticks = bar.down_ticks if bar.down_ticks is not None else 0.0
    tick_total = up_ticks + down_ticks
    net_tick_count = up_ticks - down_ticks
    tick_bias_ratio = net_tick_count / tick_total if tick_total > 0 else 0.0
    volume_per_tick = bar.volume / tick_total if tick_total > 0 else None
    force_score = tick_bias_ratio * bar.volume if tick_total > 0 else 0.0
    return MinuteForceFeatures(
        ts=bar.ts.isoformat(),
        symbol=bar.symbol,
        instrument_key=bar.instrument_key,
        contract_month=bar.contract_month,
        strike_price=bar.strike_price,
        call_put=bar.call_put,
        run_id=run_id,
        close=bar.close,
        volume=bar.volume,
        up_ticks=bar.up_ticks,
        down_ticks=bar.down_ticks,
        tick_total=tick_total,
        net_tick_count=net_tick_count,
        tick_bias_ratio=tick_bias_ratio,
        volume_per_tick=volume_per_tick,
        force_score=force_score,
    )


def compute_minute_force_feature_series(bars: list[Bar], run_id: str | None = None) -> list[MinuteForceFeatures]:
    return [compute_minute_force_features(bar, run_id=run_id) for bar in bars]
