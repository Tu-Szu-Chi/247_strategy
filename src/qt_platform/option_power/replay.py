from __future__ import annotations

from bisect import bisect_left
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import ceil
from threading import Lock
from uuid import uuid4

from qt_platform.domain import Bar, CanonicalTick
from qt_platform.option_power.aggregator import OptionPowerAggregator
from qt_platform.regime import MtxRegimeAnalyzer, regime_schema_dicts
from qt_platform.session import classify_session
from qt_platform.storage.base import BarRepository


TX_OPTION_ROOT_CANDIDATES = [
    *[f"TX{digit}" for digit in range(10)],
    *[f"TX{chr(code)}" for code in range(ord("A"), ord("Z") + 1)],
]
DAY_INDICATOR_SYMBOL = "TWII"


@dataclass(frozen=True)
class ReplaySnapshotFrame:
    index: int
    simulated_at: str
    snapshot: dict


@dataclass
class ReplaySession:
    session_id: str
    start: datetime
    end: datetime
    snapshot_interval_seconds: float
    option_root: str
    underlying_symbol: str
    selected_option_roots: list[str]
    bars: list[dict]
    indicator_series: dict[str, list[dict]]
    snapshot_datetimes: list[datetime]
    snapshot_times: list[str]
    snapshots: list[dict]

    def metadata(self) -> dict:
        return {
            "session_id": self.session_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "snapshot_interval_seconds": self.snapshot_interval_seconds,
            "option_root": self.option_root,
            "underlying_symbol": self.underlying_symbol,
            "selected_option_roots": self.selected_option_roots,
            "snapshot_count": len(self.snapshots),
            "snapshot_times": self.snapshot_times,
            "available_series": sorted(self.indicator_series.keys()),
            "regime_schema": regime_schema_dicts(),
            "bar_count": len(self.bars),
        }


class OptionPowerReplayService:
    def __init__(
        self,
        *,
        store: BarRepository,
        option_root: str,
        expiry_count: int,
        underlying_symbol: str,
        snapshot_interval_seconds: float,
    ) -> None:
        self.store = store
        self.option_root = option_root
        self.expiry_count = expiry_count
        self.underlying_symbol = underlying_symbol
        self.snapshot_interval_seconds = snapshot_interval_seconds
        self._lock = Lock()
        self._sessions: dict[str, ReplaySession] = {}
        self._default_session_id: str | None = None

    def create_session(
        self,
        *,
        start: datetime,
        end: datetime,
        set_as_default: bool = False,
    ) -> dict:
        with self._lock:
            existing = self._find_covering_session_locked(start=start, end=end)
            if existing is not None:
                if set_as_default or self._default_session_id is None:
                    self._default_session_id = existing.session_id
                return existing.metadata()

        replay_session = self._build_session(start=start, end=end)
        with self._lock:
            existing = self._find_covering_session_locked(start=start, end=end)
            if existing is not None:
                if set_as_default or self._default_session_id is None:
                    self._default_session_id = existing.session_id
                return existing.metadata()
            self._sessions[replay_session.session_id] = replay_session
            if set_as_default or self._default_session_id is None:
                self._default_session_id = replay_session.session_id
        return replay_session.metadata()

    def _find_covering_session_locked(self, *, start: datetime, end: datetime) -> ReplaySession | None:
        covering = [
            session
            for session in self._sessions.values()
            if session.start <= start and session.end >= end
        ]
        if not covering:
            return None
        return min(
            covering,
            key=lambda session: (
                (session.end - session.start).total_seconds(),
                session.start,
                session.session_id,
            ),
        )

    def get_session_metadata(self, session_id: str) -> dict | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        return session.metadata()

    def get_default_session_metadata(self) -> dict | None:
        if self._default_session_id is None:
            return None
        return self.get_session_metadata(self._default_session_id)

    def get_snapshot(self, session_id: str, index: int) -> dict | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if index < 0 or index >= len(session.snapshots):
            return None
        return {
            "session_id": session_id,
            "index": index,
            "simulated_at": session.snapshot_times[index],
            "snapshot": session.snapshots[index],
        }

    def get_bars(
        self,
        session_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
        interval: str | None = None,
    ) -> list[dict] | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        bars = _slice_bars(session.bars, start=start, end=end)
        if interval is not None and interval != "1m":
            return _aggregate_bars(bars, interval=interval)
        return bars

    def get_series(
        self,
        session_id: str,
        names: list[str],
        start: datetime | None = None,
        end: datetime | None = None,
        interval: str | None = None,
    ) -> dict[str, list[dict]] | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        payload: dict[str, list[dict]] = {}
        for name in names:
            if name in session.indicator_series:
                payload[name] = _slice_and_resample_series(
                    session.indicator_series[name],
                    start=start,
                    end=end,
                    interval=interval,
                )
        return payload

    def get_snapshot_at(self, session_id: str, ts: datetime) -> dict | None:
        session = self._sessions.get(session_id)
        if session is None or not session.snapshot_datetimes:
            return None

        idx = bisect_left(session.snapshot_datetimes, ts)
        if idx >= len(session.snapshot_datetimes):
            idx = len(session.snapshot_datetimes) - 1
        elif idx > 0:
            previous_ts = session.snapshot_datetimes[idx - 1]
            current_ts = session.snapshot_datetimes[idx]
            if abs((ts - previous_ts).total_seconds()) <= abs((current_ts - ts).total_seconds()):
                idx -= 1

        return self.get_snapshot(session_id, idx)

    def current_snapshot(self) -> dict:
        if self._default_session_id is None:
            return {
                "type": "option_power_snapshot",
                "generated_at": datetime.now().isoformat(),
                "run_id": None,
                "session": "unknown",
                "option_root": self.option_root,
                "underlying_reference_price": None,
                "underlying_reference_source": None,
                "raw_pressure": 0,
                "pressure_index": 0,
                "raw_pressure_weighted": 0,
                "pressure_index_weighted": 0,
                "regime": None,
                "iv_surface": None,
                "expiries": [],
                "contract_count": 0,
                "status": "replay_not_loaded",
                "warning": "No replay session loaded.",
            }
        session = self._sessions[self._default_session_id]
        if not session.snapshots:
            return {
                "type": "option_power_snapshot",
                "generated_at": datetime.now().isoformat(),
                "run_id": None,
                "session": "unknown",
                "option_root": self.option_root,
                "underlying_reference_price": None,
                "underlying_reference_source": None,
                "raw_pressure": 0,
                "pressure_index": 0,
                "raw_pressure_weighted": 0,
                "pressure_index_weighted": 0,
                "regime": None,
                "iv_surface": None,
                "expiries": [],
                "contract_count": 0,
                "status": "replay_empty",
                "warning": "Replay session produced no snapshots.",
            }
        return session.snapshots[0]

    def _build_session(self, *, start: datetime, end: datetime) -> ReplaySession:
        if end < start:
            raise ValueError("Replay end must be greater than or equal to start.")

        replay_symbols = [self.underlying_symbol, *TX_OPTION_ROOT_CANDIDATES]
        raw_ticks = self.store.list_ticks_for_symbols(replay_symbols, start, end)

        option_ticks = [tick for tick in raw_ticks if tick.strike_price is not None and tick.call_put is not None]
        selected_option_roots = self._select_option_roots(option_ticks)
        filtered_option_ticks = [tick for tick in option_ticks if tick.symbol in selected_option_roots]
        underlying_ticks = [tick for tick in raw_ticks if tick.symbol == self.underlying_symbol]

        replay_ticks = sorted(
            [*filtered_option_ticks, *underlying_ticks],
            key=lambda tick: (tick.ts, tick.instrument_key or "", tick.price, tick.size, tick.source),
        )

        aggregator = OptionPowerAggregator(option_root=",".join(selected_option_roots) or self.option_root)
        replay_session = classify_session(start)
        for contract in _contract_seeds(filtered_option_ticks):
            aggregator.seed_contract(
                instrument_key=contract.instrument_key or "",
                symbol=contract.symbol,
                contract_month=contract.contract_month,
                strike_price=float(contract.strike_price or 0.0),
                call_put=contract.call_put or "",
                session=replay_session if replay_session in {"day", "night"} else "day",
            )

        snapshots: list[dict] = []
        snapshot_datetimes: list[datetime] = []
        snapshot_times: list[str] = []
        latest_future_reference_price: float | None = None
        latest_day_indicator_price: float | None = None
        day_indicator_index = 0
        tick_index = 0
        boundary = start
        interval = timedelta(seconds=max(self.snapshot_interval_seconds, 1.0))
        session_id = f"replay-{datetime.now().strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}"
        day_indicator_bars = self.store.list_bars("1m", DAY_INDICATOR_SYMBOL, start, end)
        underlying_bars = self.store.list_bars("1m", self.underlying_symbol, start, end)
        underlying_tick_index = 0
        underlying_bar_index = 0
        regime = MtxRegimeAnalyzer()

        while boundary <= end:
            while tick_index < len(replay_ticks) and replay_ticks[tick_index].ts <= boundary:
                tick = replay_ticks[tick_index]
                if tick.symbol == self.underlying_symbol:
                    latest_future_reference_price = tick.price
                else:
                    aggregator.ingest_tick(tick)
                tick_index += 1

            while underlying_tick_index < len(underlying_ticks) and underlying_ticks[underlying_tick_index].ts <= boundary:
                regime.ingest_tick(underlying_ticks[underlying_tick_index])
                underlying_tick_index += 1

            while underlying_bar_index < len(underlying_bars) and underlying_bars[underlying_bar_index].ts <= boundary:
                regime.ingest_bar(underlying_bars[underlying_bar_index])
                underlying_bar_index += 1

            while day_indicator_index < len(day_indicator_bars) and day_indicator_bars[day_indicator_index].ts <= boundary:
                latest_day_indicator_price = day_indicator_bars[day_indicator_index].close
                day_indicator_index += 1

            reference_price, reference_source = _resolve_replay_reference_price(
                session=classify_session(boundary),
                latest_day_indicator_price=latest_day_indicator_price,
                latest_future_reference_price=latest_future_reference_price,
                underlying_symbol=self.underlying_symbol,
            )

            snapshot = aggregator.snapshot(
                generated_at=boundary,
                run_id=session_id,
                underlying_reference_price=reference_price,
                underlying_reference_source=reference_source,
                status="replay_ready",
                regime=regime.snapshot(boundary),
            ).to_dict()
            snapshots.append(snapshot)
            snapshot_datetimes.append(boundary)
            snapshot_times.append(boundary.isoformat())
            boundary += interval

        bars = [_bar_to_chart_dict(bar) for bar in underlying_bars]
        indicator_series = _build_indicator_series(snapshot_times, snapshots)

        return ReplaySession(
            session_id=session_id,
            start=start,
            end=end,
            snapshot_interval_seconds=self.snapshot_interval_seconds,
            option_root=self.option_root,
            underlying_symbol=self.underlying_symbol,
            selected_option_roots=selected_option_roots,
            bars=bars,
            indicator_series=indicator_series,
            snapshot_datetimes=snapshot_datetimes,
            snapshot_times=snapshot_times,
            snapshots=snapshots,
        )

    def _select_option_roots(self, ticks: list[CanonicalTick]) -> list[str]:
        if self.option_root and self.option_root.upper() not in {"AUTO", "TX", "TXO"}:
            return [self.option_root.upper()]
        by_root: dict[str, tuple[str, int]] = {}
        for tick in ticks:
            contract_month = tick.contract_month or "999999"
            existing = by_root.get(tick.symbol)
            count = 1 if existing is None else existing[1] + 1
            best_contract_month = min(contract_month, existing[0]) if existing else contract_month
            by_root[tick.symbol] = (best_contract_month, count)

        ranked = sorted(
            by_root.items(),
            key=lambda item: (item[1][0], -item[1][1], item[0]),
        )
        return [root for root, _ in ranked[: self.expiry_count]]


def _contract_seeds(ticks: list[CanonicalTick]) -> list[CanonicalTick]:
    seeds: dict[str, CanonicalTick] = {}
    for tick in ticks:
        key = tick.instrument_key or ""
        if key and key not in seeds:
            seeds[key] = tick
    return sorted(
        seeds.values(),
        key=lambda item: (item.contract_month, float(item.strike_price or 0.0), item.call_put or "", item.instrument_key or ""),
    )


def _build_indicator_series(snapshot_times: list[str], snapshots: list[dict]) -> dict[str, list[dict]]:
    series_names = [
        "pressure_index",
        "raw_pressure",
        "pressure_index_weighted",
        "raw_pressure_weighted",
        "regime_state",
        "structure_state",
        "trend_score",
        "chop_score",
        "reversal_risk",
        "vwap_distance_bps",
        "directional_efficiency_15b",
        "tick_imbalance_5b",
        "trade_intensity_ratio_30b",
        "range_ratio_5b_30b",
        "adx_14",
        "plus_di_14",
        "minus_di_14",
        "di_bias_14",
        "choppiness_14",
        "compression_score",
        "expansion_score",
        "compression_expansion_state",
        "session_cvd",
        "cvd_5b_delta",
        "cvd_15b_delta",
        "cvd_5b_slope",
        "cvd_price_alignment",
        "price_cvd_divergence_15b",
        "iv_skew",
    ]
    payload: dict[str, list[dict]] = {name: [] for name in series_names}
    drive_points: list[tuple[datetime, float]] = []
    expansion_points: list[tuple[datetime, float]] = []
    sticky_structure_state = 0
    for ts, snapshot in zip(snapshot_times, snapshots):
        ts_dt = datetime.fromisoformat(ts)
        regime = snapshot.get("regime") or {}
        drive_value = float(regime.get("directional_efficiency_15b", 0) or 0) * float(regime.get("tick_imbalance_5b", 0) or 0)
        expansion_value = float(regime.get("range_ratio_5b_30b", 0) or 0)
        drive_points.append((ts_dt, drive_value))
        expansion_points.append((ts_dt, expansion_value))
        for name in series_names:
            if name in snapshot:
                value = snapshot.get(name, 0)
            else:
                if name == "iv_skew":
                    value = _iv_surface_value(snapshot, "skew")
                elif name == "regime_state":
                    value = _regime_state_value(regime.get("regime_label"))
                elif name == "structure_state":
                    candidate = _structure_state_value(ts_dt, drive_points, expansion_points)
                    if candidate != 0:
                        sticky_structure_state = candidate
                    value = sticky_structure_state
                elif name == "compression_expansion_state":
                    value = _compression_expansion_state_value(regime.get("compression_expansion_state"))
                elif name == "cvd_price_alignment":
                    value = _cvd_price_alignment_value(regime.get("cvd_price_alignment"))
                elif name == "price_cvd_divergence_15b":
                    value = _price_cvd_divergence_value(regime.get("price_cvd_divergence_15b"))
                else:
                    value = regime.get(name, 0)
            payload[name].append({"time": ts, "value": value})
    return payload


def _iv_surface_value(snapshot: dict, field: str) -> float:
    value = (snapshot.get("iv_surface") or {}).get(field)
    return float(value) if value is not None else 0.0


def _regime_state_value(label: str | None) -> int:
    if label == "trend_up" or label == "reversal_up":
        return 1
    if label == "trend_down" or label == "reversal_down":
        return -1
    return 0


def _structure_state_value(
    now: datetime,
    drive_points: list[tuple[datetime, float]],
    expansion_points: list[tuple[datetime, float]],
) -> int:
    cutoff = now - timedelta(minutes=30)
    rolling_drive = [abs(value) for ts, value in drive_points if ts >= cutoff]
    rolling_expansion = [value for ts, value in expansion_points if ts >= cutoff]
    if not rolling_drive or not rolling_expansion:
        return 0

    drive_threshold = max(_quantile(rolling_drive, 0.65), 0.08)
    expansion_threshold = max(_quantile(rolling_expansion, 0.60), 0.12)
    current_drive = drive_points[-1][1]
    current_expansion = expansion_points[-1][1]
    if current_expansion <= expansion_threshold:
        return 0
    if current_drive > drive_threshold:
        return 1
    if current_drive < -drive_threshold:
        return -1
    return 0


def _compression_expansion_state_value(state: str | None) -> int:
    if state == "compressed":
        return -1
    if state == "expanding":
        return 1
    if state == "expanded":
        return 2
    return 0


def _cvd_price_alignment_value(state: str | None) -> int:
    if state == "aligned_up":
        return 1
    if state == "aligned_down":
        return -1
    if state == "diverged":
        return 2
    return 0


def _price_cvd_divergence_value(state: str | None) -> int:
    if state == "bullish":
        return 1
    if state == "bearish":
        return -1
    return 0


def _quantile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def _resolve_replay_reference_price(
    *,
    session: str,
    latest_day_indicator_price: float | None,
    latest_future_reference_price: float | None,
    underlying_symbol: str,
) -> tuple[float | None, str | None]:
    if session == "day":
        if latest_day_indicator_price is not None:
            return latest_day_indicator_price, DAY_INDICATOR_SYMBOL.lower()
    if latest_future_reference_price is not None:
        return latest_future_reference_price, underlying_symbol.lower()
    return None, None


def _bar_to_chart_dict(bar: Bar) -> dict:
    return {
        "time": bar.ts.isoformat(),
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
    }


def _slice_bars(bars: list[dict], *, start: datetime | None, end: datetime | None) -> list[dict]:
    if start is None and end is None:
        return bars
    sliced: list[dict] = []
    for bar in bars:
        ts = datetime.fromisoformat(bar["time"])
        if start is not None and ts < start:
            continue
        if end is not None and ts > end:
            continue
        sliced.append(bar)
    return sliced


def _aggregate_bars(bars: list[dict], *, interval: str) -> list[dict]:
    if interval == "1m":
        return bars
    buckets: OrderedDict[datetime, dict] = OrderedDict()
    for bar in bars:
        ts = datetime.fromisoformat(bar["time"])
        bucket = _bucket_datetime(ts, interval)
        existing = buckets.get(bucket)
        if existing is None:
            buckets[bucket] = {
                "time": bucket.isoformat(),
                "open": bar["open"],
                "high": bar["high"],
                "low": bar["low"],
                "close": bar["close"],
                "volume": bar.get("volume", 0),
            }
            continue
        existing["high"] = max(existing["high"], bar["high"])
        existing["low"] = min(existing["low"], bar["low"])
        existing["close"] = bar["close"]
        existing["volume"] = existing.get("volume", 0) + bar.get("volume", 0)
    return list(buckets.values())


def _slice_and_resample_series(
    points: list[dict],
    *,
    start: datetime | None,
    end: datetime | None,
    interval: str | None,
) -> list[dict]:
    if interval is None:
        return [
            point
            for point in points
            if (start is None or datetime.fromisoformat(point["time"]) >= start)
            and (end is None or datetime.fromisoformat(point["time"]) <= end)
        ]
    buckets: OrderedDict[datetime, dict] = OrderedDict()
    for point in points:
        ts = datetime.fromisoformat(point["time"])
        if start is not None and ts < start:
            continue
        if end is not None and ts > end:
            continue
        bucket = _bucket_datetime(ts, interval)
        buckets[bucket] = {
            "time": bucket.isoformat(),
            "value": point["value"],
        }
    return list(buckets.values())


def _bucket_datetime(ts: datetime, interval: str) -> datetime:
    if interval == "1m":
        return ts.replace(second=0, microsecond=0)
    if interval == "5m":
        minute = ts.minute - (ts.minute % 5)
        return ts.replace(minute=minute, second=0, microsecond=0)
    if interval == "15m":
        minute = ts.minute - (ts.minute % 15)
        return ts.replace(minute=minute, second=0, microsecond=0)
    if interval == "30m":
        minute = ts.minute - (ts.minute % 30)
        return ts.replace(minute=minute, second=0, microsecond=0)
    raise ValueError(f"Unsupported replay interval: {interval}")
