from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Lock
from uuid import uuid4

from qt_platform.domain import Bar, CanonicalTick
from qt_platform.option_power.aggregator import OptionPowerAggregator
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
        replay_session = self._build_session(start=start, end=end)
        with self._lock:
            self._sessions[replay_session.session_id] = replay_session
            if set_as_default or self._default_session_id is None:
                self._default_session_id = replay_session.session_id
        return replay_session.metadata()

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

    def get_bars(self, session_id: str) -> list[dict] | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        return session.bars

    def get_series(self, session_id: str, names: list[str]) -> dict[str, list[dict]] | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        payload: dict[str, list[dict]] = {}
        for name in names:
            if name in session.indicator_series:
                payload[name] = session.indicator_series[name]
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
                "raw_pressure_1m": 0,
                "pressure_index_1m": 0,
                "pressure_index_5m": 0,
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
                "raw_pressure_1m": 0,
                "pressure_index_1m": 0,
                "pressure_index_5m": 0,
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
        tick_index = 0
        boundary = start
        interval = timedelta(seconds=max(self.snapshot_interval_seconds, 1.0))
        session_id = f"replay-{datetime.now().strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}"
        day_indicator_bars = self.store.list_bars("1m", DAY_INDICATOR_SYMBOL, start, end)

        while boundary <= end:
            while tick_index < len(replay_ticks) and replay_ticks[tick_index].ts <= boundary:
                tick = replay_ticks[tick_index]
                if tick.symbol == self.underlying_symbol:
                    latest_future_reference_price = tick.price
                else:
                    aggregator.ingest_tick(tick)
                tick_index += 1

            reference_price, reference_source = _resolve_replay_reference_price(
                boundary=boundary,
                session=classify_session(boundary),
                day_indicator_bars=day_indicator_bars,
                latest_future_reference_price=latest_future_reference_price,
                underlying_symbol=self.underlying_symbol,
            )

            snapshot = aggregator.snapshot(
                generated_at=boundary,
                run_id=session_id,
                underlying_reference_price=reference_price,
                underlying_reference_source=reference_source,
                status="replay_ready",
            ).to_dict()
            snapshots.append(snapshot)
            snapshot_datetimes.append(boundary)
            snapshot_times.append(boundary.isoformat())
            boundary += interval

        bars = [_bar_to_chart_dict(bar) for bar in self.store.list_bars("1m", self.underlying_symbol, start, end)]
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
        "pressure_index_5m",
        "raw_pressure",
        "pressure_index",
        "raw_pressure_1m",
        "pressure_index_1m",
    ]
    payload: dict[str, list[dict]] = {name: [] for name in series_names}
    for ts, snapshot in zip(snapshot_times, snapshots):
        for name in series_names:
            payload[name].append({"time": ts, "value": snapshot.get(name, 0)})
    return payload


def _resolve_replay_reference_price(
    *,
    boundary: datetime,
    session: str,
    day_indicator_bars: list[Bar],
    latest_future_reference_price: float | None,
    underlying_symbol: str,
) -> tuple[float | None, str | None]:
    if session == "day":
        day_price = _latest_bar_close_before(day_indicator_bars, boundary)
        if day_price is not None:
            return day_price, DAY_INDICATOR_SYMBOL.lower()
    if latest_future_reference_price is not None:
        return latest_future_reference_price, underlying_symbol.lower()
    return None, None


def _latest_bar_close_before(bars: list[Bar], boundary: datetime) -> float | None:
    latest_close = None
    for bar in bars:
        if bar.ts > boundary:
            break
        latest_close = bar.close
    return latest_close


def _bar_to_chart_dict(bar: Bar) -> dict:
    return {
        "time": bar.ts.isoformat(),
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
    }
