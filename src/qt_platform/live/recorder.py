from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from qt_platform.domain import Bar, CanonicalTick
from qt_platform.features import compute_minute_force_feature_series
from qt_platform.live.base import BaseLiveProvider, LiveUsageStatus
from qt_platform.storage.base import BarRepository


@dataclass(frozen=True)
class LiveRecordResult:
    ticks_appended: int
    bars_upserted: int
    first_tick_ts: str | None
    last_tick_ts: str | None
    run_id: str | None = None
    stop_reason: str | None = None
    usage_status: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class LiveRecorderService:
    def __init__(self, provider: BaseLiveProvider, store: BarRepository) -> None:
        self.provider = provider
        self.store = store

    def record(
        self,
        symbols: list[str],
        max_events: int | None = None,
        batch_size: int = 500,
        run_id: str | None = None,
    ) -> LiveRecordResult:
        self.provider.connect()
        usage_before = self.provider.usage_status()
        try:
            ticks = self.provider.stream_ticks(symbols=symbols, max_events=max_events)
            result = self.persist_tick_stream(
                ticks,
                usage_before=usage_before,
                batch_size=batch_size,
                run_id=run_id,
            )
            usage_after = self.provider.usage_status()
        finally:
            self.provider.close()

        stop_reason = self.provider.stop_reason()
        final_usage = usage_after or usage_before
        return LiveRecordResult(
            run_id=run_id,
            ticks_appended=result.ticks_appended,
            bars_upserted=result.bars_upserted,
            first_tick_ts=result.first_tick_ts,
            last_tick_ts=result.last_tick_ts,
            stop_reason=stop_reason,
            usage_status=final_usage.to_dict() if final_usage else None,
        )

    def persist_ticks(
        self,
        ticks: list[CanonicalTick],
        stop_reason: str | None = None,
        usage_status: LiveUsageStatus | None = None,
        run_id: str | None = None,
    ) -> LiveRecordResult:
        ticks_appended = self.store.append_ticks(ticks)
        bars = aggregate_ticks_to_bars(ticks)
        bars_upserted = self.store.upsert_bars("1m", bars)
        self.store.upsert_minute_force_features(
            compute_minute_force_feature_series(bars, run_id=run_id)
        )
        return LiveRecordResult(
            run_id=run_id,
            ticks_appended=ticks_appended,
            bars_upserted=bars_upserted,
            first_tick_ts=ticks[0].ts.isoformat() if ticks else None,
            last_tick_ts=ticks[-1].ts.isoformat() if ticks else None,
            stop_reason=stop_reason,
            usage_status=usage_status.to_dict() if usage_status else None,
        )

    def persist_tick_stream(
        self,
        ticks: Iterable[CanonicalTick],
        usage_before: LiveUsageStatus | None = None,
        batch_size: int = 500,
        run_id: str | None = None,
    ) -> LiveRecordResult:
        total_ticks = 0
        total_bars = 0
        first_tick_ts: str | None = None
        last_tick_ts: str | None = None
        batch: list[CanonicalTick] = []

        for tick in ticks:
            if first_tick_ts is None:
                first_tick_ts = tick.ts.isoformat()
            last_tick_ts = tick.ts.isoformat()
            batch.append(tick)
            if len(batch) >= batch_size:
                total_ticks += self.store.append_ticks(batch)
                bars = aggregate_ticks_to_bars(batch)
                total_bars += self.store.upsert_bars("1m", bars)
                self.store.upsert_minute_force_features(
                    compute_minute_force_feature_series(bars, run_id=run_id)
                )
                batch = []

        if batch:
            total_ticks += self.store.append_ticks(batch)
            bars = aggregate_ticks_to_bars(batch)
            total_bars += self.store.upsert_bars("1m", bars)
            self.store.upsert_minute_force_features(
                compute_minute_force_feature_series(bars, run_id=run_id)
            )

        return LiveRecordResult(
            run_id=run_id,
            ticks_appended=total_ticks,
            bars_upserted=total_bars,
            first_tick_ts=first_tick_ts,
            last_tick_ts=last_tick_ts,
            usage_status=usage_before.to_dict() if usage_before else None,
        )


def aggregate_ticks_to_bars(ticks: list[CanonicalTick]) -> list[Bar]:
    grouped: dict[tuple, list[CanonicalTick]] = {}
    for tick in ticks:
        minute_ts = tick.ts.replace(second=0, microsecond=0)
        key = (
            minute_ts,
            tick.trading_day,
            tick.symbol,
            tick.instrument_key or tick.symbol,
            tick.contract_month,
            tick.strike_price,
            tick.call_put,
            tick.session,
            tick.source,
        )
        grouped.setdefault(key, []).append(tick)

    bars: list[Bar] = []
    for key, minute_ticks in sorted(grouped.items(), key=lambda item: item[0][0]):
        minute_ticks.sort(key=lambda tick: tick.ts)
        prices = [tick.price for tick in minute_ticks]
        bars.append(
            Bar(
                ts=key[0],
                trading_day=key[1],
                symbol=key[2],
                instrument_key=key[3],
                contract_month=key[4],
                strike_price=key[5],
                call_put=key[6],
                session=key[7],
                open=prices[0],
                high=max(prices),
                low=min(prices),
                close=prices[-1],
                volume=sum(tick.size for tick in minute_ticks),
                open_interest=None,
                source=key[8],
                up_ticks=sum(1 for tick in minute_ticks if tick.tick_direction == "up"),
                down_ticks=sum(1 for tick in minute_ticks if tick.tick_direction == "down"),
                build_source="live_tick_agg",
            )
        )
    return bars
