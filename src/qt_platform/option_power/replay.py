from __future__ import annotations

from bisect import bisect_left
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from math import ceil
from threading import Lock, Thread, Timer
from typing import Callable
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
    snapshot_count: int
    available_series: list[str]
    compute_status: str = "pending"
    computed_until: datetime | None = None
    progress_ratio: float = 0.0
    checkpoint_count: int = 0
    target_window_bars: int = 200
    compute_error: str | None = None
    frame_cache: OrderedDict[datetime, dict] = field(default_factory=OrderedDict)
    window_cache: OrderedDict[tuple, dict] = field(default_factory=OrderedDict)

    def metadata(self) -> dict:
        return {
            "session_id": self.session_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "snapshot_interval_seconds": self.snapshot_interval_seconds,
            "option_root": self.option_root,
            "underlying_symbol": self.underlying_symbol,
            "selected_option_roots": self.selected_option_roots,
            "snapshot_count": self.snapshot_count,
            "available_series": sorted(self.available_series),
            "regime_schema": regime_schema_dicts(),
            "bar_count": None,
            "cache_mode": "memory",
            "loaded_window_count": len(self.window_cache),
            "supports_windowed_loading": True,
            "compute_status": self.compute_status,
            "computed_until": self.computed_until.isoformat() if self.computed_until is not None else None,
            "progress_ratio": self.progress_ratio,
            "checkpoint_count": self.checkpoint_count,
            "target_window_bars": self.target_window_bars,
            "compute_error": self.compute_error,
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
        self._max_cached_windows = 24
        self._compute_threads: dict[str, Thread] = {}

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
            self._start_background_compute_locked(replay_session)
        return replay_session.metadata()

    def wait_until_ready(self, session_id: str, timeout: float = 30.0) -> bool:
        thread = self._compute_threads.get(session_id)
        if thread is None:
            session = self._sessions.get(session_id)
            return session is not None and session.compute_status == "ready"
        thread.join(timeout)
        session = self._sessions.get(session_id)
        return session is not None and session.compute_status == "ready"

    def get_progress(self, session_id: str) -> dict | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        return _progress_payload(session)

    def _start_background_compute_locked(self, session: ReplaySession) -> None:
        if session.session_id in self._compute_threads:
            return
        thread = Timer(0.001, self._run_background_compute, args=(session.session_id,))
        thread.name = f"option-power-replay-{session.session_id}"
        thread.daemon = True
        self._compute_threads[session.session_id] = thread
        thread.start()

    def _run_background_compute(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            return
        with self._lock:
            session.compute_status = "running"
            session.compute_error = None

        try:
            interval_seconds = max(session.snapshot_interval_seconds, 1.0)
            checkpoint_every = max(1, min(120, ceil(600 / interval_seconds)))

            def on_snapshot(snapshot_ts: datetime, snapshot: dict) -> None:
                snapshot_index = max(0, int((snapshot_ts - session.start).total_seconds() // interval_seconds))
                with self._lock:
                    session.frame_cache[snapshot_ts] = snapshot
                    session.computed_until = snapshot_ts
                    session.progress_ratio = min(1.0, (snapshot_index + 1) / max(session.snapshot_count, 1))
                    session.checkpoint_count = (snapshot_index + 1) // checkpoint_every

            self._build_window_frames(
                session,
                start=session.start,
                end=session.end,
                on_snapshot=on_snapshot,
            )
            with self._lock:
                session.compute_status = "ready"
                session.computed_until = session.end if session.snapshot_count > 0 else None
                session.progress_ratio = 1.0
        except Exception as exc:  # pragma: no cover - defensive background boundary
            with self._lock:
                session.compute_status = "failed"
                session.compute_error = str(exc)

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
        if index < 0 or index >= session.snapshot_count:
            return None
        snapshot_at = session.start + timedelta(seconds=max(session.snapshot_interval_seconds, 1.0) * index)
        if snapshot_at > session.end:
            snapshot_at = session.end
        payload = self.get_snapshot_at(session_id, snapshot_at)
        if payload is None:
            return None
        return {
            "session_id": session_id,
            "index": index,
            "simulated_at": payload["simulated_at"],
            "snapshot": payload["snapshot"],
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
        resolved_start, resolved_end = _resolve_window(session, start, end)
        query_start, query_end = _expand_window_for_interval(resolved_start, resolved_end, interval)
        cache_key = ("bars", query_start, query_end, interval or "1m")
        cached = self._cache_get(session, cache_key)
        if cached is not None:
            return cached["bars"]
        source_bars = self.store.list_bars("1m", session.underlying_symbol, query_start, query_end)
        bars = [_bar_to_chart_dict(bar) for bar in source_bars if bar.session != "unknown"]
        if interval is not None and interval != "1m":
            bars = _aggregate_bars(bars, interval=interval)
        self._cache_put(session, cache_key, {"bars": bars})
        return bars

    def get_series(
        self,
        session_id: str,
        names: list[str],
        start: datetime | None = None,
        end: datetime | None = None,
        interval: str | None = None,
    ) -> dict[str, list[dict]] | None:
        payload = self.get_series_payload(
            session_id,
            names,
            start=start,
            end=end,
            interval=interval,
        )
        if payload is None:
            return None
        return payload["series"]

    def get_series_payload(
        self,
        session_id: str,
        names: list[str],
        start: datetime | None = None,
        end: datetime | None = None,
        interval: str | None = None,
    ) -> dict | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        resolved_start, resolved_end = _resolve_window(session, start, end)
        query_start, query_end = _expand_window_for_interval(resolved_start, resolved_end, interval)
        interval_key = interval or "1m"
        names_key = tuple(sorted(set(names)))
        cache_key = ("series", query_start, query_end, interval_key, names_key)
        cached = self._cache_get(session, cache_key)
        if cached is not None:
            return {
                "series": cached["series"],
                **_progress_payload(session),
                "partial": _is_partial(session, query_end),
            }

        snapshot_datetimes, snapshots = self._cached_frames_in_window(
            session,
            start=query_start,
            end=query_end,
        )
        snapshot_times = [snapshot["generated_at"] for snapshot in snapshots]
        indicator_series = _build_indicator_series(snapshot_times, snapshots)
        payload: dict[str, list[dict]] = {}
        for name in names:
            if name in indicator_series:
                payload[name] = _slice_and_resample_series(
                    indicator_series[name],
                    start=query_start,
                    end=query_end,
                    interval=interval,
                )
        partial = _is_partial(session, query_end)
        if not partial:
            self._cache_put(session, cache_key, {"series": payload})
        return {
            "series": payload,
            **_progress_payload(session),
            "partial": partial,
        }

    def get_bundle(
        self,
        session_id: str,
        names: list[str],
        start: datetime | None = None,
        end: datetime | None = None,
        interval: str | None = None,
    ) -> dict | None:
        bars = self.get_bars(session_id, start=start, end=end, interval=interval)
        series_payload = self.get_series_payload(
            session_id,
            names,
            start=start,
            end=end,
            interval=interval,
        )
        if bars is None or series_payload is None:
            return None
        return {
            "bars": bars,
            "series": series_payload["series"],
            "status": series_payload["status"],
            "partial": series_payload["partial"],
            "computed_until": series_payload["computed_until"],
            "compute_status": series_payload["compute_status"],
            "progress_ratio": series_payload["progress_ratio"],
            "checkpoint_count": series_payload["checkpoint_count"],
        }

    def get_bundle_by_bars(
        self,
        session_id: str,
        names: list[str],
        *,
        anchor: datetime,
        direction: str,
        bar_count: int,
        interval: str | None = None,
    ) -> dict | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if direction not in {"prev", "next", "around"}:
            raise ValueError(f"Unsupported replay bar direction: {direction}")
        if bar_count <= 0:
            raise ValueError("Replay bar_count must be greater than 0.")

        bars = self._cursor_bars(
            session,
            anchor=anchor,
            direction=direction,
            bar_count=bar_count,
            interval=interval,
        )
        selected_bars = _select_bars_by_cursor(
            bars,
            anchor=anchor,
            direction=direction,
            bar_count=bar_count,
        )
        coverage = _bar_cursor_coverage(
            bars,
            selected_bars,
            anchor=anchor,
            direction=direction,
            interval=interval or "1m",
        )
        if not selected_bars:
            return {
                "bars": [],
                "series": {name: [] for name in names},
                **_progress_payload(session),
                "partial": False,
                "coverage": coverage,
                "session": session.metadata(),
            }

        selected_start = datetime.fromisoformat(selected_bars[0]["time"])
        selected_end = datetime.fromisoformat(selected_bars[-1]["time"])
        if selected_start < session.start or selected_end > session.end:
            progress = _progress_payload(session)
            return {
                "bars": selected_bars,
                "series": {name: [] for name in names},
                "status": progress["status"],
                "partial": True,
                "computed_until": progress["computed_until"],
                "compute_status": progress["compute_status"],
                "progress_ratio": progress["progress_ratio"],
                "checkpoint_count": progress["checkpoint_count"],
                "coverage": coverage,
                "session": session.metadata(),
            }

        series_payload = self.get_series_payload(
            session_id,
            names,
            start=selected_start,
            end=selected_end,
            interval=interval,
        )
        if series_payload is None:
            return None
        return {
            "bars": selected_bars,
            "series": series_payload["series"],
            "status": series_payload["status"],
            "partial": series_payload["partial"],
            "computed_until": series_payload["computed_until"],
            "compute_status": series_payload["compute_status"],
            "progress_ratio": series_payload["progress_ratio"],
            "checkpoint_count": series_payload["checkpoint_count"],
            "coverage": coverage,
            "session": session.metadata(),
        }

    def get_snapshot_at(self, session_id: str, ts: datetime) -> dict | None:
        session = self._sessions.get(session_id)
        if session is None or session.snapshot_count <= 0:
            return None

        snapshot_datetimes = _snapshot_datetimes(session)
        idx = bisect_left(snapshot_datetimes, ts)
        if idx >= len(snapshot_datetimes):
            idx = len(snapshot_datetimes) - 1
        elif idx > 0:
            previous_ts = snapshot_datetimes[idx - 1]
            current_ts = snapshot_datetimes[idx]
            if abs((ts - previous_ts).total_seconds()) <= abs((current_ts - ts).total_seconds()):
                idx -= 1

        snapshot_ts = snapshot_datetimes[idx]
        cache_key = ("snapshot", snapshot_ts)
        cached = self._cache_get(session, cache_key)
        if cached is not None:
            return cached["payload"]
        snapshots = self._cached_frame(session, snapshot_ts)
        if snapshots is None:
            return None
        payload = {
            "session_id": session_id,
            "index": idx,
            "simulated_at": snapshot_ts.isoformat(),
            "snapshot": snapshots,
        }
        self._cache_put(session, cache_key, {"payload": payload})
        return payload

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
        if session.snapshot_count <= 0:
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
        payload = self.get_snapshot(session.session_id, 0)
        if payload is None:
            status = "replay_pending" if session.compute_status in {"pending", "running"} else "replay_empty"
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
                "expiries": [],
                "contract_count": 0,
                "status": status,
                "warning": "Replay session compute is not ready." if status == "replay_pending" else "Replay session produced no snapshots.",
            }
        return payload["snapshot"]

    def _build_session(self, *, start: datetime, end: datetime) -> ReplaySession:
        if end < start:
            raise ValueError("Replay end must be greater than or equal to start.")

        replay_symbols = [self.underlying_symbol, *TX_OPTION_ROOT_CANDIDATES]
        selected_option_roots = self._select_option_roots_from_store(replay_symbols, start, end)
        interval_seconds = max(self.snapshot_interval_seconds, 1.0)
        snapshot_count = int((end - start).total_seconds() // interval_seconds) + 1
        session_id = f"replay-{datetime.now().strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}"

        return ReplaySession(
            session_id=session_id,
            start=start,
            end=end,
            snapshot_interval_seconds=self.snapshot_interval_seconds,
            option_root=self.option_root,
            underlying_symbol=self.underlying_symbol,
            selected_option_roots=selected_option_roots,
            snapshot_count=snapshot_count,
            available_series=_indicator_series_names(),
        )

    def _build_window_frames(
        self,
        session: ReplaySession,
        *,
        start: datetime,
        end: datetime,
        on_snapshot: Callable[[datetime, dict], None] | None = None,
    ) -> tuple[list[datetime], list[dict]]:
        replay_symbols = [session.underlying_symbol, *session.selected_option_roots]
        raw_ticks = self.store.list_ticks_for_symbols(replay_symbols, session.start, end)

        option_ticks = [
            tick
            for tick in raw_ticks
            if tick.symbol in session.selected_option_roots and tick.strike_price is not None and tick.call_put is not None
        ]
        underlying_ticks = [tick for tick in raw_ticks if tick.symbol == session.underlying_symbol]

        replay_ticks = sorted(
            [*option_ticks, *underlying_ticks],
            key=lambda tick: (tick.ts, tick.instrument_key or "", tick.price, tick.size, tick.source),
        )

        aggregator = OptionPowerAggregator(option_root=",".join(session.selected_option_roots) or session.option_root)
        replay_session = classify_session(session.start)
        for contract in _contract_seeds(option_ticks):
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
        latest_future_reference_price: float | None = None
        latest_day_indicator_price: float | None = None
        day_indicator_index = 0
        tick_index = 0
        boundary = session.start
        interval = timedelta(seconds=max(session.snapshot_interval_seconds, 1.0))
        day_indicator_bars = self.store.list_bars("1m", DAY_INDICATOR_SYMBOL, session.start, end)
        underlying_bars = self.store.list_bars("1m", session.underlying_symbol, session.start, end)
        underlying_tick_index = 0
        underlying_bar_index = 0
        regime = MtxRegimeAnalyzer()

        while boundary <= end:
            while tick_index < len(replay_ticks) and replay_ticks[tick_index].ts <= boundary:
                tick = replay_ticks[tick_index]
                if tick.symbol == session.underlying_symbol:
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
                underlying_symbol=session.underlying_symbol,
            )

            snapshot = aggregator.snapshot(
                generated_at=boundary,
                run_id=session.session_id,
                underlying_reference_price=reference_price,
                underlying_reference_source=reference_source,
                status="replay_ready",
                regime=regime.snapshot(boundary),
            ).to_dict()
            if boundary >= start:
                snapshots.append(snapshot)
                snapshot_datetimes.append(boundary)
                if on_snapshot is not None:
                    on_snapshot(boundary, snapshot)
            boundary += interval

        return snapshot_datetimes, snapshots

    def _cached_frame(self, session: ReplaySession, snapshot_ts: datetime) -> dict | None:
        with self._lock:
            return session.frame_cache.get(snapshot_ts)

    def _cached_frames_in_window(
        self,
        session: ReplaySession,
        *,
        start: datetime,
        end: datetime,
    ) -> tuple[list[datetime], list[dict]]:
        with self._lock:
            items = [
                (snapshot_ts, snapshot)
                for snapshot_ts, snapshot in session.frame_cache.items()
                if start <= snapshot_ts <= end
            ]
        items.sort(key=lambda item: item[0])
        return [item[0] for item in items], [item[1] for item in items]

    def _cursor_bars(
        self,
        session: ReplaySession,
        *,
        anchor: datetime,
        direction: str,
        bar_count: int,
        interval: str | None,
    ) -> list[dict]:
        if direction == "around":
            start = anchor - timedelta(days=7)
            end = anchor + timedelta(days=7)
            return self._bars_from_store(start=start, end=end, session=session, interval=interval)

        for days in (1, 3, 7, 14, 30, 90):
            if direction == "prev":
                start = anchor - timedelta(days=days)
                end = max(anchor, session.end)
            else:
                start = min(anchor, session.start)
                end = anchor + timedelta(days=days)
            bars = self._bars_from_store(start=start, end=end, session=session, interval=interval)
            selected = _select_bars_by_cursor(
                bars,
                anchor=anchor,
                direction=direction,
                bar_count=bar_count,
            )
            if len(selected) >= bar_count:
                return bars
        return bars

    def _bars_from_store(
        self,
        *,
        start: datetime,
        end: datetime,
        session: ReplaySession,
        interval: str | None,
    ) -> list[dict]:
        query_start, query_end = _expand_window_for_interval(start, end, interval)
        source_bars = self.store.list_bars("1m", session.underlying_symbol, query_start, query_end)
        bars = [_bar_to_chart_dict(bar) for bar in source_bars if bar.session != "unknown"]
        if interval is not None and interval != "1m":
            bars = _aggregate_bars(bars, interval=interval)
        return bars

    def _select_option_roots_from_store(self, symbols: list[str], start: datetime, end: datetime) -> list[str]:
        if self.option_root and self.option_root.upper() not in {"AUTO", "TX", "TXO"}:
            return [self.option_root.upper()]
        if hasattr(self.store, "list_tick_symbol_stats"):
            stats = self.store.list_tick_symbol_stats(symbols, start, end)
            return self._select_option_roots_from_stats(stats)
        raw_ticks = self.store.list_ticks_for_symbols(symbols, start, end)
        option_ticks = [tick for tick in raw_ticks if tick.strike_price is not None and tick.call_put is not None]
        return self._select_option_roots(option_ticks)

    def _select_option_roots_from_stats(self, stats: list[dict]) -> list[str]:
        ranked = sorted(
            ((item["symbol"], item["first_contract_month"], item["tick_count"]) for item in stats if item.get("symbol") != self.underlying_symbol),
            key=lambda item: (item[1] or "999999", -int(item[2] or 0), item[0]),
        )
        return [root for root, _, _ in ranked[: self.expiry_count]]

    def _cache_get(self, session: ReplaySession, key: tuple) -> dict | None:
        with self._lock:
            cached = session.window_cache.get(key)
            if cached is None:
                return None
            session.window_cache.move_to_end(key)
            return cached

    def _cache_put(self, session: ReplaySession, key: tuple, value: dict) -> None:
        with self._lock:
            session.window_cache[key] = value
            session.window_cache.move_to_end(key)
            while len(session.window_cache) > self._max_cached_windows:
                session.window_cache.popitem(last=False)

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


def _indicator_series_names() -> list[str]:
    return [
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


def _build_indicator_series(snapshot_times: list[str], snapshots: list[dict]) -> dict[str, list[dict]]:
    series_names = _indicator_series_names()
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


def _resolve_window(
    session: ReplaySession,
    start: datetime | None,
    end: datetime | None,
) -> tuple[datetime, datetime]:
    resolved_start = max(start, session.start) if start is not None else session.start
    resolved_end = min(end, session.end) if end is not None else session.end
    if resolved_end < resolved_start:
        resolved_end = resolved_start
    return resolved_start, resolved_end


def _progress_payload(session: ReplaySession) -> dict:
    status = session.compute_status
    return {
        "status": "partial" if status == "running" and session.computed_until is not None else status,
        "compute_status": status,
        "computed_until": session.computed_until.isoformat() if session.computed_until is not None else None,
        "progress_ratio": session.progress_ratio,
        "checkpoint_count": session.checkpoint_count,
    }


def _is_partial(session: ReplaySession, end: datetime) -> bool:
    if session.compute_status == "ready":
        return False
    if session.computed_until is None:
        return True
    return session.computed_until < end


def _snapshot_datetimes(session: ReplaySession) -> list[datetime]:
    interval = timedelta(seconds=max(session.snapshot_interval_seconds, 1.0))
    return [session.start + interval * index for index in range(session.snapshot_count)]


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


def _select_bars_by_cursor(
    bars: list[dict],
    *,
    anchor: datetime,
    direction: str,
    bar_count: int,
) -> list[dict]:
    if direction == "next":
        return [bar for bar in bars if datetime.fromisoformat(bar["time"]) > anchor][:bar_count]
    if direction == "prev":
        return [bar for bar in bars if datetime.fromisoformat(bar["time"]) < anchor][-bar_count:]
    if direction == "around":
        half = max(1, bar_count // 2)
        previous_bars = [bar for bar in bars if datetime.fromisoformat(bar["time"]) < anchor][-half:]
        current_and_next = [bar for bar in bars if datetime.fromisoformat(bar["time"]) >= anchor]
        return [*previous_bars, *current_and_next[: max(0, bar_count - len(previous_bars))]]
    raise ValueError(f"Unsupported replay bar direction: {direction}")


def _bar_cursor_coverage(
    bars: list[dict],
    selected_bars: list[dict],
    *,
    anchor: datetime,
    direction: str,
    interval: str,
) -> dict:
    first_bar_time = selected_bars[0]["time"] if selected_bars else None
    last_bar_time = selected_bars[-1]["time"] if selected_bars else None
    if not bars:
        return {
            "anchor": anchor.isoformat(),
            "direction": direction,
            "interval": interval,
            "bar_count": 0,
            "first_bar_time": None,
            "last_bar_time": None,
            "has_prev": False,
            "has_next": False,
        }
    first_available = datetime.fromisoformat(bars[0]["time"])
    last_available = datetime.fromisoformat(bars[-1]["time"])
    if selected_bars:
        first_selected = datetime.fromisoformat(selected_bars[0]["time"])
        last_selected = datetime.fromisoformat(selected_bars[-1]["time"])
    else:
        first_selected = anchor
        last_selected = anchor
    return {
        "anchor": anchor.isoformat(),
        "direction": direction,
        "interval": interval,
        "bar_count": len(selected_bars),
        "first_bar_time": first_bar_time,
        "last_bar_time": last_bar_time,
        "has_prev": first_selected > first_available,
        "has_next": last_selected < last_available,
    }


def _expand_window_for_interval(
    start: datetime,
    end: datetime,
    interval: str | None,
) -> tuple[datetime, datetime]:
    if interval is None or interval == "1m":
        return start, end
    bucket_start = _bucket_datetime(start, interval)
    bucket_end = _bucket_datetime(end, interval) + _interval_timedelta(interval) - timedelta(microseconds=1)
    return bucket_start, bucket_end


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


def _interval_timedelta(interval: str) -> timedelta:
    if interval == "1m":
        return timedelta(minutes=1)
    if interval == "5m":
        return timedelta(minutes=5)
    if interval == "15m":
        return timedelta(minutes=15)
    if interval == "30m":
        return timedelta(minutes=30)
    raise ValueError(f"Unsupported replay interval: {interval}")
