from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
from math import ceil
from pathlib import Path
from threading import Lock, Thread, Timer
from time import perf_counter
from typing import Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

from qt_platform.domain import Bar, CanonicalTick
from qt_platform.monitor.aggregator import MonitorAggregator
from qt_platform.monitor.indicator_backend import (
    INDICATOR_SERIES_NAMES,
    build_indicator_series,
    compression_expansion_state_value,
    cvd_price_alignment_value,
    price_cvd_divergence_value,
    regime_state_value,
    rolling_quantile,
    structure_state_value,
)
from qt_platform.regime import MtxRegimeAnalyzer, regime_schema_dicts
from qt_platform.session import classify_session, session_windows_for, trading_day_for
from qt_platform.storage.base import BarRepository


TX_OPTION_ROOT_CANDIDATES = [
    *[f"TX{digit}" for digit in range(10)],
    *[f"TX{chr(code)}" for code in range(ord("A"), ord("Z") + 1)],
]
DAY_INDICATOR_SYMBOL = "TWII"
LOCAL_TIMEZONE = ZoneInfo("Asia/Taipei")
STATE_SERIES_NAMES = {
    "regime_state",
    "structure_state",
    "compression_expansion_state",
    "cvd_price_alignment",
    "price_cvd_divergence_15b",
    "trend_bias_state",
    "flow_state",
    "range_state",
}
PRESSURE_SERIES_NAMES = {
    "pressure_index",
    "raw_pressure",
    "pressure_index_weighted",
    "raw_pressure_weighted",
}


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
    available_start: datetime
    available_end: datetime
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
    indicator_cache: dict[str, list[dict]] = field(default_factory=dict)
    indicator_cache_frame_count: int = 0
    indicator_cache_start: datetime | None = None
    indicator_cache_until: datetime | None = None
    window_cache: OrderedDict[tuple, dict] = field(default_factory=OrderedDict)
    chart_series_cache: OrderedDict[tuple, dict] = field(default_factory=OrderedDict)
    chart_state_cache: OrderedDict[tuple, "ChartStateCheckpoint"] = field(default_factory=OrderedDict)
    chart_input_cache: OrderedDict[tuple, list] = field(default_factory=OrderedDict)

    def metadata(self) -> dict:
        return {
            "session_id": self.session_id,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "available_start": self.available_start.isoformat(),
            "available_end": self.available_end.isoformat(),
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
            "indicator_cache_start": self.indicator_cache_start.isoformat() if self.indicator_cache_start is not None else None,
            "indicator_cache_until": self.indicator_cache_until.isoformat() if self.indicator_cache_until is not None else None,
            "indicator_cache_frame_count": self.indicator_cache_frame_count,
            "progress_ratio": self.progress_ratio,
            "checkpoint_count": self.checkpoint_count,
            "target_window_bars": self.target_window_bars,
            "compute_error": self.compute_error,
        }


@dataclass(frozen=True)
class ChartStateCheckpoint:
    session_window_start: datetime
    interval: str
    include_regime: bool
    processed_until: datetime
    aggregator: MonitorAggregator
    regime: MtxRegimeAnalyzer | None
    latest_future_reference_price: float | None
    latest_day_indicator_price: float | None


class MonitorReplayService:
    def __init__(
        self,
        *,
        store: BarRepository,
        option_root: str,
        expiry_count: int,
        underlying_symbol: str,
        snapshot_interval_seconds: float,
        external_indicator_series: dict[str, list[dict]] | None = None,
    ) -> None:
        self.store = store
        self.option_root = option_root
        self.expiry_count = expiry_count
        self.underlying_symbol = underlying_symbol
        self.snapshot_interval_seconds = snapshot_interval_seconds
        self.external_indicator_series = _normalize_external_indicator_series(external_indicator_series or {})
        self._lock = Lock()
        self._sessions: dict[str, ReplaySession] = {}
        self._default_session_id: str | None = None
        self._max_cached_windows = 24
        self._max_cached_chart_windows = 24
        self._max_cached_chart_states = 96
        self._max_cached_chart_inputs = 48
        self._compute_threads: dict[str, Thread] = {}

    def create_session(
        self,
        *,
        start: datetime,
        end: datetime,
        available_start: datetime | None = None,
        available_end: datetime | None = None,
        set_as_default: bool = False,
    ) -> dict:
        start = _as_naive_local_datetime(start)
        end = _as_naive_local_datetime(end)
        available_start = _as_naive_local_datetime(available_start) if available_start is not None else start
        available_end = _as_naive_local_datetime(available_end) if available_end is not None else end
        with self._lock:
            existing = self._find_covering_session_locked(start=start, end=end)
            if existing is not None:
                if set_as_default or self._default_session_id is None:
                    self._default_session_id = existing.session_id
                return existing.metadata()

        replay_session = self._build_session(
            start=start,
            end=end,
            available_start=available_start,
            available_end=available_end,
        )
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

    def build_backtest_indicator_series(
        self,
        *,
        start: datetime,
        end: datetime,
        names: list[str] | None = None,
        interval: str | None = "1m",
        wait_timeout: float | None = None,
        set_as_default: bool = False,
    ) -> dict[str, list[dict]]:
        start = _as_naive_local_datetime(start)
        end = _as_naive_local_datetime(end)
        metadata = self.create_session(start=start, end=end, set_as_default=set_as_default)
        session_id = metadata["session_id"]
        resolved_timeout = wait_timeout
        if resolved_timeout is None:
            resolved_timeout = max(30.0, (end - start).total_seconds())
        ready = self.wait_until_ready(session_id, timeout=resolved_timeout)
        progress = self.get_progress(session_id) or {}
        if progress.get("compute_status") == "failed":
            session = self._sessions.get(session_id)
            detail = f": {session.compute_error}" if session is not None and session.compute_error else ""
            raise RuntimeError(f"Option-power indicator replay failed{detail}")
        if not ready:
            raise TimeoutError(
                f"Option-power indicator replay did not finish within {resolved_timeout:.1f}s "
                f"(status={progress.get('compute_status')})."
            )

        payload = self.get_series_payload(
            session_id,
            names or _indicator_series_names(),
            start=start,
            end=end,
            interval=interval,
        )
        if payload is None:
            return {}
        return payload["series"]

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
        max_points: int | None = None,
    ) -> list[dict] | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        resolved_start, resolved_end = _resolve_window(session, start, end)
        query_start, query_end = _expand_window_for_interval(resolved_start, resolved_end, interval)
        cache_key = ("bars", query_start, query_end, interval or "1m", max_points or 0)
        cached = self._cache_get(session, cache_key)
        if cached is not None:
            return cached["bars"]
        source_bars = self.store.list_bars("1m", session.underlying_symbol, query_start, query_end)
        bars = [_bar_to_chart_dict(bar) for bar in source_bars if bar.session != "unknown"]
        if interval is not None and interval != "1m":
            bars = _aggregate_bars(bars, interval=interval)
        bars = _downsample_bars(bars, max_points=max_points)
        self._cache_put(session, cache_key, {"bars": bars})
        return bars

    def get_series(
        self,
        session_id: str,
        names: list[str],
        start: datetime | None = None,
        end: datetime | None = None,
        interval: str | None = None,
        max_points: int | None = None,
    ) -> dict[str, list[dict]] | None:
        payload = self.get_series_payload(
            session_id,
            names,
            start=start,
            end=end,
            interval=interval,
            max_points=max_points,
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
        max_points: int | None = None,
        request_id: str | None = None,
    ) -> dict | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        resolved_start, resolved_end = _resolve_window(session, start, end)
        query_start, query_end = _expand_window_for_interval(resolved_start, resolved_end, interval)
        if interval is not None:
            return self._get_chart_series_payload(
                session,
                names=names,
                resolved_start=resolved_start,
                resolved_end=resolved_end,
                query_start=query_start,
                query_end=query_end,
                interval=interval,
                max_points=max_points,
                request_id=request_id,
            )
        self._ensure_frames_for_window(session, query_start, query_end)
        interval_key = interval or "1m"
        names_key = tuple(sorted(set(names)))
        cache_key = ("series", query_start, query_end, interval_key, names_key, max_points or 0)
        cached = self._cache_get(session, cache_key)
        if cached is not None:
            return {
                "series": cached["series"],
                "coverage": cached["coverage"],
                **_progress_payload(session),
                "partial": not self._window_is_cached(session, query_start, query_end),
            }

        indicator_series = self._indicator_cache_for_session(session)
        payload: dict[str, list[dict]] = {}
        for name in names:
            if name in indicator_series:
                payload[name] = _slice_and_resample_series(
                    indicator_series[name],
                    start=query_start,
                    end=query_end,
                    interval=interval,
                )
                payload[name] = _downsample_series(
                    payload[name],
                    name=name,
                    max_points=max_points,
                )
            elif name in self.external_indicator_series:
                payload[name] = _downsample_series(
                    _slice_and_resample_series(
                        self.external_indicator_series[name],
                        start=query_start,
                        end=query_end,
                        interval=interval,
                    ),
                    name=name,
                    max_points=max_points,
                )
        partial = not self._window_is_cached(session, query_start, query_end)
        coverage = _series_coverage(
            session,
            requested_start=resolved_start,
            requested_end=resolved_end,
            query_start=query_start,
            query_end=query_end,
            complete=not partial,
            max_points=max_points,
            request_id=request_id,
        )
        if not partial:
            self._cache_put(session, cache_key, {"series": payload, "coverage": coverage})
        return {
            "series": payload,
            "coverage": coverage,
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
        max_points: int | None = None,
        request_id: str | None = None,
    ) -> dict | None:
        bars = self.get_bars(session_id, start=start, end=end, interval=interval, max_points=max_points)
        series_payload = self.get_series_payload(
            session_id,
            names,
            start=start,
            end=end,
            interval=interval,
            request_id=request_id,
        )
        if bars is None or series_payload is None:
            return None
        return {
            "bars": bars,
            "series": series_payload["series"],
            "coverage": series_payload["coverage"],
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
        max_points: int | None = None,
        request_id: str | None = None,
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
                "series_coverage": _series_coverage(
                    session,
                    requested_start=anchor,
                    requested_end=anchor,
                    query_start=anchor,
                    query_end=anchor,
                    request_id=request_id,
                ),
                **_progress_payload(session),
                "partial": False,
                "coverage": coverage,
                "session": session.metadata(),
            }

        selected_start = datetime.fromisoformat(selected_bars[0]["time"])
        selected_end = datetime.fromisoformat(selected_bars[-1]["time"])
        response_bars = _downsample_bars(selected_bars, max_points=max_points)
        if selected_start < session.available_start or selected_end > session.available_end:
            progress = _progress_payload(session)
            return {
                "bars": response_bars,
                "series": {name: [] for name in names},
                "series_coverage": _series_coverage(
                    session,
                    requested_start=selected_start,
                    requested_end=selected_end,
                    query_start=selected_start,
                    query_end=selected_end,
                    complete=False,
                    request_id=request_id,
                ),
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
            request_id=request_id,
        )
        if series_payload is None:
            return None
        return {
            "bars": response_bars,
            "series": series_payload["series"],
            "series_coverage": series_payload["coverage"],
            "status": series_payload["status"],
            "partial": series_payload["partial"],
            "computed_until": series_payload["computed_until"],
            "compute_status": series_payload["compute_status"],
            "progress_ratio": series_payload["progress_ratio"],
            "checkpoint_count": series_payload["checkpoint_count"],
            "coverage": coverage,
            "session": session.metadata(),
        }

    def profile_chart_series_payload(
        self,
        session_id: str,
        names: list[str],
        *,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> dict | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        resolved_start, resolved_end = _resolve_window(session, start, end)
        query_start, query_end = _expand_window_for_interval(resolved_start, resolved_end, interval)
        profile: dict[str, float | int | None | str] = {
            "requested_start": resolved_start.isoformat(),
            "requested_end": resolved_end.isoformat(),
            "query_start": query_start.isoformat(),
            "query_end": query_end.isoformat(),
            "interval": interval,
            "include_regime": int(_series_requires_regime(names)),
            "include_iv_surface": int("iv_skew" in names),
            "tick_fetch_db_seconds": 0.0,
            "tick_fetch_decode_seconds": 0.0,
            "tick_rows_fetched": 0,
            "bar_fetch_db_seconds": 0.0,
            "bar_fetch_decode_seconds": 0.0,
            "bar_rows_fetched": 0,
            "contract_seed_seconds": 0.0,
            "replay_loop_seconds": 0.0,
            "indicator_snapshot_seconds": 0.0,
            "indicator_series_build_seconds": 0.0,
            "evaluation_points": 0,
            "window_count": 0,
        }
        started = perf_counter()
        series = self._build_chart_series_window(
            session,
            start=query_start,
            end=query_end,
            interval=interval,
            include_regime=bool(profile["include_regime"]),
            include_iv_surface=bool(profile["include_iv_surface"]),
            profile=profile,
        )
        total_seconds = perf_counter() - started
        return {
            "series_row_count": len(series.get("raw_pressure", [])),
            "profile": profile,
            "total_seconds": total_seconds,
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

    def _build_session(
        self,
        *,
        start: datetime,
        end: datetime,
        available_start: datetime,
        available_end: datetime,
    ) -> ReplaySession:
        if end < start:
            raise ValueError("Replay end must be greater than or equal to start.")
        if available_end < available_start:
            raise ValueError("Replay available_end must be greater than or equal to available_start.")
        if start < available_start or end > available_end:
            raise ValueError("Replay view range must be inside the available replay range.")

        replay_symbols = [self.underlying_symbol, *TX_OPTION_ROOT_CANDIDATES]
        selected_option_roots = self._select_option_roots_from_store(replay_symbols, start, end)
        interval_seconds = max(self.snapshot_interval_seconds, 1.0)
        snapshot_count = int((end - start).total_seconds() // interval_seconds) + 1
        session_id = f"replay-{datetime.now().strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}"

        return ReplaySession(
            session_id=session_id,
            start=start,
            end=end,
            available_start=available_start,
            available_end=available_end,
            snapshot_interval_seconds=self.snapshot_interval_seconds,
            option_root=self.option_root,
            underlying_symbol=self.underlying_symbol,
            selected_option_roots=selected_option_roots,
            snapshot_count=snapshot_count,
            available_series=_indicator_series_names(self.external_indicator_series),
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
        raw_ticks = self.store.list_ticks_for_symbols(replay_symbols, start, end)

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

        aggregator = MonitorAggregator(option_root=",".join(session.selected_option_roots) or session.option_root)
        replay_session = classify_session(start)
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
        boundary = start
        interval = timedelta(seconds=max(session.snapshot_interval_seconds, 1.0))
        day_indicator_bars = self.store.list_bars("1m", DAY_INDICATOR_SYMBOL, start, end)
        underlying_bars = self.store.list_bars("1m", session.underlying_symbol, start, end)
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

    def _indicator_cache_for_session(self, session: ReplaySession) -> dict[str, list[dict]]:
        while True:
            with self._lock:
                cached_frame_count = session.indicator_cache_frame_count
                frame_count = len(session.frame_cache)
                if cached_frame_count == frame_count:
                    return session.indicator_cache
                items = list(session.frame_cache.items())

            items.sort(key=lambda item: item[0])
            snapshot_times = [snapshot["generated_at"] for _, snapshot in items]
            snapshots = [snapshot for _, snapshot in items]
            indicator_series = _build_indicator_series(snapshot_times, snapshots)
            cache_start = items[0][0] if items else None
            cache_until = items[-1][0] if items else None

            with self._lock:
                if len(session.frame_cache) == frame_count:
                    session.indicator_cache = indicator_series
                    session.indicator_cache_frame_count = frame_count
                    session.indicator_cache_start = cache_start
                    session.indicator_cache_until = cache_until
                    return session.indicator_cache

    def _get_chart_series_payload(
        self,
        session: ReplaySession,
        *,
        names: list[str],
        resolved_start: datetime,
        resolved_end: datetime,
        query_start: datetime,
        query_end: datetime,
        interval: str,
        max_points: int | None,
        request_id: str | None,
    ) -> dict:
        builtin_names = [name for name in names if name not in self.external_indicator_series]
        include_regime = _series_requires_regime(builtin_names)
        include_iv_surface = "iv_skew" in builtin_names
        cache_key = (
            "chart-series",
            query_start,
            query_end,
            interval,
            int(include_regime),
            int(include_iv_surface),
        )
        cached = self._chart_cache_get(session, cache_key)
        if cached is None and builtin_names:
            indicator_series = self._build_chart_series_window(
                session,
                start=query_start,
                end=query_end,
                interval=interval,
                include_regime=include_regime,
                include_iv_surface=include_iv_surface,
            )
            self._chart_cache_put(
                session,
                cache_key,
                {
                    "series": indicator_series,
                    "coverage": _series_coverage(
                        session,
                        requested_start=resolved_start,
                        requested_end=resolved_end,
                        query_start=query_start,
                        query_end=query_end,
                        complete=True,
                        computed_start=query_start,
                        computed_until=query_end,
                        frame_count=len(indicator_series.get("raw_pressure", [])),
                    ),
                },
            )
            cached = self._chart_cache_get(session, cache_key)
        if cached is None:
            cached = {
                "series": {},
                "coverage": _series_coverage(
                    session,
                    requested_start=resolved_start,
                    requested_end=resolved_end,
                    query_start=query_start,
                    query_end=query_end,
                    complete=True,
                    computed_start=query_start,
                    computed_until=query_end,
                    frame_count=0,
                ),
            }

        payload: dict[str, list[dict]] = {}
        for name in names:
            if name in cached["series"]:
                points = list(cached["series"].get(name, []))
            else:
                points = _slice_and_resample_series(
                    self.external_indicator_series.get(name, []),
                    start=query_start,
                    end=query_end,
                    interval=interval,
                )
            payload[name] = _downsample_series(points, name=name, max_points=max_points)
        coverage = dict(cached["coverage"])
        coverage["request_id"] = request_id
        return {
            "series": payload,
            "coverage": coverage,
            **_progress_payload(session),
            "partial": False,
        }

    def _build_chart_series_window(
        self,
        session: ReplaySession,
        *,
        start: datetime,
        end: datetime,
        interval: str,
        include_regime: bool,
        include_iv_surface: bool,
        profile: dict | None = None,
    ) -> dict[str, list[dict]]:
        snapshot_times: list[str] = []
        snapshots: list[dict] = []
        for window_start, window_end in _overlapping_replay_session_windows(start, end):
            emit_start = max(start, window_start)
            emit_end = min(end, window_end)
            if emit_end < emit_start:
                continue
            if profile is not None:
                profile["window_count"] = int(profile.get("window_count", 0) or 0) + 1
            window_times, window_snapshots = self._materialize_chart_session_window(
                session,
                warm_start=window_start,
                warm_end=window_end,
                emit_start=emit_start,
                emit_end=emit_end,
                interval=interval,
                include_regime=include_regime,
                include_iv_surface=include_iv_surface,
                profile=profile,
            )
            snapshot_times.extend(window_times)
            snapshots.extend(window_snapshots)
        build_started = perf_counter()
        indicator_series = _build_indicator_series(snapshot_times, snapshots)
        if profile is not None:
            profile["indicator_series_build_seconds"] = (
                float(profile.get("indicator_series_build_seconds", 0.0) or 0.0)
                + (perf_counter() - build_started)
            )
        return indicator_series

    def _materialize_chart_session_window(
        self,
        session: ReplaySession,
        *,
        warm_start: datetime,
        warm_end: datetime,
        emit_start: datetime,
        emit_end: datetime,
        interval: str,
        include_regime: bool,
        include_iv_surface: bool,
        profile: dict | None = None,
    ) -> tuple[list[str], list[dict]]:
        checkpoint = self._chart_state_checkpoint_get(
            session,
            session_window_start=warm_start,
            interval=interval,
            include_regime=include_regime,
            not_after=emit_start,
        )
        cache_end = emit_end
        replay_start = warm_start
        latest_future_reference_price: float | None = None
        latest_day_indicator_price: float | None = None
        raw_ticks: list[CanonicalTick] | None = None
        day_indicator_bars: list[Bar] = []
        if classify_session(warm_start) == "day" and replay_start <= emit_end:
            day_indicator_bars = self._session_symbol_bars(
                session,
                symbol=DAY_INDICATOR_SYMBOL,
                window_start=warm_start,
                window_end=warm_end,
                start=replay_start,
                end=emit_end,
                cache_end=cache_end,
                profile=profile,
            )
        needs_underlying_ticks = include_regime or classify_session(warm_start) != "day" or not day_indicator_bars
        if checkpoint is not None:
            aggregator = checkpoint.aggregator.clone()
            replay_start = checkpoint.processed_until + timedelta(microseconds=1)
            latest_future_reference_price = checkpoint.latest_future_reference_price
            latest_day_indicator_price = checkpoint.latest_day_indicator_price
            if include_regime:
                regime = checkpoint.regime.clone() if checkpoint.regime is not None else MtxRegimeAnalyzer()
            else:
                regime = MtxRegimeAnalyzer()
        else:
            aggregator = MonitorAggregator(option_root=",".join(session.selected_option_roots) or session.option_root)
            replay_session = classify_session(warm_start)
            raw_ticks = self._session_replay_ticks(
                session,
                window_start=warm_start,
                window_end=warm_end,
                start=warm_start,
                end=emit_end,
                cache_end=cache_end,
                include_underlying=needs_underlying_ticks,
                profile=profile,
            )
            seed_started = perf_counter()
            option_seed_ticks = [
                tick
                for tick in raw_ticks
                if tick.symbol in session.selected_option_roots and tick.strike_price is not None and tick.call_put is not None
            ]
            for contract in _contract_seeds(option_seed_ticks):
                aggregator.seed_contract(
                    instrument_key=contract.instrument_key or "",
                    symbol=contract.symbol,
                    contract_month=contract.contract_month,
                    strike_price=float(contract.strike_price or 0.0),
                    call_put=contract.call_put or "",
                    session=replay_session if replay_session in {"day", "night"} else "day",
                )
            if profile is not None:
                profile["contract_seed_seconds"] = (
                    float(profile.get("contract_seed_seconds", 0.0) or 0.0)
                    + (perf_counter() - seed_started)
                )
            regime = MtxRegimeAnalyzer()

        if raw_ticks is None:
            raw_ticks = self._session_replay_ticks(
                session,
                window_start=warm_start,
                window_end=warm_end,
                start=replay_start,
                end=emit_end,
                cache_end=cache_end,
                include_underlying=needs_underlying_ticks,
                profile=profile,
            ) if replay_start <= emit_end else []
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

        underlying_bars: list[Bar] = []
        if include_regime and replay_start <= emit_end:
            underlying_bars = self._session_symbol_bars(
                session,
                symbol=session.underlying_symbol,
                window_start=warm_start,
                window_end=warm_end,
                start=replay_start,
                end=emit_end,
                cache_end=cache_end,
                profile=profile,
            )

        evaluation_times = _interval_evaluation_points(emit_start, emit_end, interval)
        snapshot_times: list[str] = []
        snapshots: list[dict] = []
        day_indicator_index = 0
        tick_index = 0
        underlying_tick_index = 0
        underlying_bar_index = 0
        last_processed_until = checkpoint.processed_until if checkpoint is not None else None

        replay_started = perf_counter()
        for bucket_start, evaluation_time in evaluation_times:
            while tick_index < len(replay_ticks) and replay_ticks[tick_index].ts <= evaluation_time:
                tick = replay_ticks[tick_index]
                if tick.symbol == session.underlying_symbol:
                    latest_future_reference_price = tick.price
                else:
                    aggregator.ingest_tick(tick)
                tick_index += 1

            if include_regime:
                while underlying_tick_index < len(underlying_ticks) and underlying_ticks[underlying_tick_index].ts <= evaluation_time:
                    regime.ingest_tick(underlying_ticks[underlying_tick_index])
                    underlying_tick_index += 1

                while underlying_bar_index < len(underlying_bars) and underlying_bars[underlying_bar_index].ts <= evaluation_time:
                    regime.ingest_bar(underlying_bars[underlying_bar_index])
                    underlying_bar_index += 1

            while day_indicator_index < len(day_indicator_bars) and day_indicator_bars[day_indicator_index].ts <= evaluation_time:
                latest_day_indicator_price = day_indicator_bars[day_indicator_index].close
                day_indicator_index += 1

            reference_price, reference_source = _resolve_replay_reference_price(
                session=classify_session(evaluation_time),
                latest_day_indicator_price=latest_day_indicator_price,
                latest_future_reference_price=latest_future_reference_price,
                underlying_symbol=session.underlying_symbol,
            )

            snapshot_times.append(bucket_start.isoformat())
            snapshot_started = perf_counter()
            snapshots.append(
                aggregator.indicator_snapshot(
                    generated_at=evaluation_time,
                    underlying_reference_price=reference_price,
                    underlying_reference_source=reference_source,
                    regime=regime.snapshot(evaluation_time) if include_regime else None,
                    include_iv_surface=include_iv_surface,
                )
            )
            if profile is not None:
                profile["indicator_snapshot_seconds"] = (
                    float(profile.get("indicator_snapshot_seconds", 0.0) or 0.0)
                    + (perf_counter() - snapshot_started)
                )
            last_processed_until = evaluation_time
        if profile is not None:
            profile["replay_loop_seconds"] = (
                float(profile.get("replay_loop_seconds", 0.0) or 0.0)
                + (perf_counter() - replay_started)
            )
            profile["evaluation_points"] = int(profile.get("evaluation_points", 0) or 0) + len(evaluation_times)

        if last_processed_until is not None:
            self._chart_state_checkpoint_put(
                session,
                ChartStateCheckpoint(
                    session_window_start=warm_start,
                    interval=interval,
                    include_regime=include_regime,
                    processed_until=last_processed_until,
                    aggregator=aggregator.clone(),
                    regime=regime.clone() if include_regime else None,
                    latest_future_reference_price=latest_future_reference_price,
                    latest_day_indicator_price=latest_day_indicator_price,
                ),
            )

        return snapshot_times, snapshots

    def _ensure_frames_for_window(
        self,
        session: ReplaySession,
        start: datetime,
        end: datetime,
    ) -> None:
        bounded_start = max(start, session.available_start)
        bounded_end = min(end, session.available_end)
        if bounded_end < bounded_start:
            return
        for missing_start, missing_end in self._missing_frame_ranges(session, bounded_start, bounded_end):
            self._cache_window_frames(session, start=missing_start, end=missing_end)

    def _cache_window_frames(
        self,
        session: ReplaySession,
        *,
        start: datetime,
        end: datetime,
    ) -> None:
        interval_seconds = max(session.snapshot_interval_seconds, 1.0)

        def on_snapshot(snapshot_ts: datetime, snapshot: dict) -> None:
            with self._lock:
                session.frame_cache[snapshot_ts] = snapshot
                session.computed_until = max(session.computed_until or snapshot_ts, snapshot_ts)
                if session.start <= snapshot_ts <= session.end and session.snapshot_count > 0:
                    snapshot_index = max(0, int((snapshot_ts - session.start).total_seconds() // interval_seconds))
                    session.progress_ratio = max(
                        session.progress_ratio,
                        min(1.0, (snapshot_index + 1) / max(session.snapshot_count, 1)),
                    )

        self._build_window_frames(
            session,
            start=start,
            end=end,
            on_snapshot=on_snapshot,
        )

    def _window_is_cached(
        self,
        session: ReplaySession,
        start: datetime,
        end: datetime,
    ) -> bool:
        if end < start:
            return True
        interval = timedelta(seconds=max(session.snapshot_interval_seconds, 1.0))
        with self._lock:
            cached_times = set(session.frame_cache.keys())
        boundary = start
        while boundary <= end:
            if boundary not in cached_times:
                return False
            boundary += interval
        return True

    def _missing_frame_ranges(
        self,
        session: ReplaySession,
        start: datetime,
        end: datetime,
    ) -> list[tuple[datetime, datetime]]:
        if end < start:
            return []
        interval = timedelta(seconds=max(session.snapshot_interval_seconds, 1.0))
        with self._lock:
            cached_times = set(session.frame_cache.keys())

        ranges: list[tuple[datetime, datetime]] = []
        missing_start: datetime | None = None
        boundary = start
        while boundary <= end:
            if boundary not in cached_times:
                if missing_start is None:
                    missing_start = boundary
            elif missing_start is not None:
                ranges.append((missing_start, boundary - interval))
                missing_start = None
            boundary += interval
        if missing_start is not None:
            ranges.append((missing_start, end))
        return ranges

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
                end = anchor
            else:
                start = anchor
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
        start = max(start, session.available_start)
        end = min(end, session.available_end)
        if end < start:
            return []
        query_start, query_end = _expand_window_for_interval(start, end, interval)
        source_bars = self.store.list_bars("1m", session.underlying_symbol, query_start, query_end)
        bars = [_bar_to_chart_dict(bar) for bar in source_bars if bar.session != "unknown"]
        if interval is not None and interval != "1m":
            bars = _aggregate_bars(bars, interval=interval)
        return bars

    def _session_replay_ticks(
        self,
        session: ReplaySession,
        *,
        window_start: datetime,
        window_end: datetime,
        start: datetime,
        end: datetime,
        cache_end: datetime,
        include_underlying: bool = True,
        profile: dict | None = None,
    ) -> list[CanonicalTick]:
        bounded_start = max(start, session.available_start)
        bounded_end = min(end, session.available_end)
        bounded_cache_end = min(cache_end, session.available_end, window_end)
        if bounded_end < bounded_start or bounded_cache_end < bounded_start:
            return []
        cache_prefix = ("chart-ticks",)
        cached = self._chart_input_cache_get_covering(
            session,
            prefix=cache_prefix,
            start=bounded_start,
            end=bounded_end,
        )
        if cached is None:
            replay_symbols = list(session.selected_option_roots)
            if include_underlying:
                replay_symbols = [session.underlying_symbol, *replay_symbols]
            fetch_end = max(bounded_end, bounded_cache_end)
            profiled = getattr(self.store, "list_ticks_for_symbols_replay_profiled", None)
            if callable(profiled):
                cached, fetch_profile = profiled(replay_symbols, bounded_start, fetch_end)
            else:
                fetch_started = perf_counter()
                cached = self.store.list_ticks_for_symbols(replay_symbols, bounded_start, fetch_end)
                fetch_profile = {
                    "db_fetch_seconds": perf_counter() - fetch_started,
                    "decode_seconds": None,
                    "row_count": len(cached),
                }
            if profile is not None:
                profile["tick_fetch_db_seconds"] = (
                    float(profile.get("tick_fetch_db_seconds", 0.0) or 0.0)
                    + float(fetch_profile.get("db_fetch_seconds") or 0.0)
                )
                profile["tick_fetch_decode_seconds"] = (
                    float(profile.get("tick_fetch_decode_seconds", 0.0) or 0.0)
                    + float(fetch_profile.get("decode_seconds") or 0.0)
                )
                profile["tick_rows_fetched"] = int(profile.get("tick_rows_fetched", 0) or 0) + int(fetch_profile.get("row_count") or 0)
            self._chart_input_cache_put(session, ("chart-ticks", bounded_start, fetch_end), cached)
        return _slice_ticks(cached, start=bounded_start, end=bounded_end)

    def _session_symbol_bars(
        self,
        session: ReplaySession,
        *,
        symbol: str,
        window_start: datetime,
        window_end: datetime,
        start: datetime,
        end: datetime,
        cache_end: datetime,
        profile: dict | None = None,
    ) -> list[Bar]:
        bounded_start = max(start, session.available_start)
        bounded_end = min(end, session.available_end)
        bounded_cache_end = min(cache_end, session.available_end, window_end)
        if bounded_end < bounded_start or bounded_cache_end < bounded_start:
            return []
        cache_prefix = ("chart-bars", symbol)
        cached = self._chart_input_cache_get_covering(
            session,
            prefix=cache_prefix,
            start=bounded_start,
            end=bounded_end,
        )
        if cached is None:
            fetch_end = max(bounded_end, bounded_cache_end)
            profiled = getattr(self.store, "list_bars_profiled", None)
            if callable(profiled):
                cached, fetch_profile = profiled("1m", symbol, bounded_start, fetch_end)
            else:
                fetch_started = perf_counter()
                cached = self.store.list_bars("1m", symbol, bounded_start, fetch_end)
                fetch_profile = {
                    "db_fetch_seconds": perf_counter() - fetch_started,
                    "decode_seconds": None,
                    "row_count": len(cached),
                }
            if profile is not None:
                profile["bar_fetch_db_seconds"] = (
                    float(profile.get("bar_fetch_db_seconds", 0.0) or 0.0)
                    + float(fetch_profile.get("db_fetch_seconds") or 0.0)
                )
                profile["bar_fetch_decode_seconds"] = (
                    float(profile.get("bar_fetch_decode_seconds", 0.0) or 0.0)
                    + float(fetch_profile.get("decode_seconds") or 0.0)
                )
                profile["bar_rows_fetched"] = int(profile.get("bar_rows_fetched", 0) or 0) + int(fetch_profile.get("row_count") or 0)
            self._chart_input_cache_put(session, ("chart-bars", symbol, bounded_start, fetch_end), cached)
        return _slice_bars_objects(cached, start=bounded_start, end=bounded_end)

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

    def _chart_cache_get(self, session: ReplaySession, key: tuple) -> dict | None:
        with self._lock:
            cached = session.chart_series_cache.get(key)
            if cached is None:
                return None
            session.chart_series_cache.move_to_end(key)
            return cached

    def _chart_cache_put(self, session: ReplaySession, key: tuple, value: dict) -> None:
        with self._lock:
            session.chart_series_cache[key] = value
            session.chart_series_cache.move_to_end(key)
            while len(session.chart_series_cache) > self._max_cached_chart_windows:
                session.chart_series_cache.popitem(last=False)

    def _chart_state_checkpoint_get(
        self,
        session: ReplaySession,
        *,
        session_window_start: datetime,
        interval: str,
        include_regime: bool,
        not_after: datetime,
    ) -> ChartStateCheckpoint | None:
        best_key: tuple | None = None
        best_checkpoint: ChartStateCheckpoint | None = None
        with self._lock:
            for key, checkpoint in session.chart_state_cache.items():
                _, key_window_start, key_interval, key_include_regime, key_processed_until = key
                if key_window_start != session_window_start or key_interval != interval:
                    continue
                if key_processed_until > not_after:
                    continue
                if include_regime and not key_include_regime:
                    continue
                if best_checkpoint is None or checkpoint.processed_until > best_checkpoint.processed_until:
                    best_key = key
                    best_checkpoint = checkpoint
            if best_key is not None:
                session.chart_state_cache.move_to_end(best_key)
        return best_checkpoint

    def _chart_state_checkpoint_put(
        self,
        session: ReplaySession,
        checkpoint: ChartStateCheckpoint,
    ) -> None:
        key = (
            "chart-state",
            checkpoint.session_window_start,
            checkpoint.interval,
            checkpoint.include_regime,
            checkpoint.processed_until,
        )
        with self._lock:
            session.chart_state_cache[key] = checkpoint
            session.chart_state_cache.move_to_end(key)
            while len(session.chart_state_cache) > self._max_cached_chart_states:
                session.chart_state_cache.popitem(last=False)

    def _chart_input_cache_get(self, session: ReplaySession, key: tuple) -> list | None:
        with self._lock:
            cached = session.chart_input_cache.get(key)
            if cached is None:
                return None
            session.chart_input_cache.move_to_end(key)
            return cached

    def _chart_input_cache_get_covering(
        self,
        session: ReplaySession,
        *,
        prefix: tuple,
        start: datetime,
        end: datetime,
    ) -> list | None:
        best_key: tuple | None = None
        best_value: list | None = None
        with self._lock:
            for key, cached in session.chart_input_cache.items():
                if key[:len(prefix)] != prefix:
                    continue
                cached_start = key[-2]
                cached_end = key[-1]
                if cached_start > start or cached_end < end:
                    continue
                if best_key is None or (cached_end - cached_start) < (best_key[-1] - best_key[-2]):
                    best_key = key
                    best_value = cached
            if best_key is not None:
                session.chart_input_cache.move_to_end(best_key)
        return best_value

    def _chart_input_cache_put(self, session: ReplaySession, key: tuple, value: list) -> None:
        with self._lock:
            session.chart_input_cache[key] = value
            session.chart_input_cache.move_to_end(key)
            while len(session.chart_input_cache) > self._max_cached_chart_inputs:
                session.chart_input_cache.popitem(last=False)

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


def load_external_indicator_series(path: str | Path | None) -> dict[str, list[dict]]:
    if path is None:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("series"), dict):
        return _normalize_external_indicator_series(payload["series"])
    if isinstance(payload, dict):
        return _normalize_external_indicator_series(payload)
    raise ValueError("External indicator JSON must be an object or contain a 'series' object.")


def _indicator_series_names(external_series: dict[str, list[dict]] | None = None) -> list[str]:
    names = set(INDICATOR_SERIES_NAMES)
    names.update((external_series or {}).keys())
    return sorted(names)


def _normalize_external_indicator_series(series: dict[str, list[dict]]) -> dict[str, list[dict]]:
    normalized: dict[str, list[dict]] = {}
    for name, points in series.items():
        if not isinstance(name, str) or not isinstance(points, list):
            continue
        rows: list[dict] = []
        for point in points:
            if not isinstance(point, dict):
                continue
            raw_time = point.get("time")
            if raw_time is None or point.get("value") is None:
                continue
            ts = raw_time if isinstance(raw_time, datetime) else datetime.fromisoformat(str(raw_time))
            rows.append({"time": ts.isoformat(), "value": float(point["value"])})
        rows.sort(key=lambda item: item["time"])
        normalized[name] = rows
    return normalized


def _build_indicator_series(snapshot_times: list[str], snapshots: list[dict]) -> dict[str, list[dict]]:
    return build_indicator_series(snapshot_times, snapshots)


def _series_requires_regime(names: list[str]) -> bool:
    return any(name not in PRESSURE_SERIES_NAMES and name != "iv_skew" for name in names)


def _iv_surface_value(snapshot: dict, field: str) -> float:
    value = (snapshot.get("iv_surface") or {}).get(field)
    return float(value) if value is not None else 0.0


def _regime_state_value(label: str | None) -> int:
    return regime_state_value(label)


def _structure_state_value(
    now: datetime,
    drive_points: list[tuple[datetime, float]],
    expansion_points: list[tuple[datetime, float]],
) -> int:
    return structure_state_value(now, drive_points, expansion_points)


def _compression_expansion_state_value(state: str | None) -> int:
    return compression_expansion_state_value(state)


def _cvd_price_alignment_value(state: str | None) -> int:
    return cvd_price_alignment_value(state)


def _price_cvd_divergence_value(state: str | None) -> int:
    return price_cvd_divergence_value(state)


def _quantile(values: list[float], quantile: float) -> float:
    return rolling_quantile(values, quantile)


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
    start = _as_naive_local_datetime(start) if start is not None else None
    end = _as_naive_local_datetime(end) if end is not None else None
    resolved_start = max(start, session.available_start) if start is not None else session.available_start
    resolved_end = min(end, session.available_end) if end is not None else session.available_end
    if resolved_end < resolved_start:
        resolved_end = resolved_start
    return resolved_start, resolved_end


def _as_naive_local_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(LOCAL_TIMEZONE).replace(tzinfo=None)


def _series_coverage(
    session: ReplaySession,
    *,
    requested_start: datetime,
    requested_end: datetime,
    query_start: datetime,
    query_end: datetime,
    complete: bool | None = None,
    computed_start: datetime | None = None,
    computed_until: datetime | None = None,
    frame_count: int | None = None,
    max_points: int | None = None,
    request_id: str | None = None,
) -> dict:
    resolved_computed_start = computed_start if computed_start is not None else session.indicator_cache_start
    resolved_computed_until = computed_until if computed_until is not None else (session.indicator_cache_until or session.computed_until)
    if complete is None:
        complete = (
            session.compute_status == "ready"
            or (resolved_computed_until is not None and resolved_computed_until >= query_end)
        )
    return {
        "requested_start": requested_start.isoformat(),
        "requested_end": requested_end.isoformat(),
        "query_start": query_start.isoformat(),
        "query_end": query_end.isoformat(),
        "computed_start": resolved_computed_start.isoformat() if resolved_computed_start is not None else None,
        "computed_until": resolved_computed_until.isoformat() if resolved_computed_until is not None else None,
        "complete": complete,
        "frame_count": frame_count if frame_count is not None else session.indicator_cache_frame_count,
        "max_points": max_points,
        "request_id": request_id,
    }


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


def _slice_ticks(
    ticks: list[CanonicalTick],
    *,
    start: datetime,
    end: datetime,
) -> list[CanonicalTick]:
    if end < start or not ticks:
        return []
    timestamps = [tick.ts for tick in ticks]
    start_index = bisect_left(timestamps, start)
    end_index = bisect_right(timestamps, end)
    return ticks[start_index:end_index]


def _slice_bars_objects(
    bars: list[Bar],
    *,
    start: datetime,
    end: datetime,
) -> list[Bar]:
    if end < start or not bars:
        return []
    timestamps = [bar.ts for bar in bars]
    start_index = bisect_left(timestamps, start)
    end_index = bisect_right(timestamps, end)
    return bars[start_index:end_index]


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


def _downsample_bars(bars: list[dict], *, max_points: int | None) -> list[dict]:
    if max_points is None or max_points <= 0 or len(bars) <= max_points:
        return bars
    bucket_size = ceil(len(bars) / max_points)
    sampled: list[dict] = []
    for index in range(0, len(bars), bucket_size):
        bucket = bars[index:index + bucket_size]
        if not bucket:
            continue
        sampled.append(
            {
                "time": bucket[0]["time"],
                "open": bucket[0]["open"],
                "high": max(item["high"] for item in bucket),
                "low": min(item["low"] for item in bucket),
                "close": bucket[-1]["close"],
                "volume": sum(item.get("volume", 0) for item in bucket),
            }
        )
    return sampled


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


def _downsample_series(
    points: list[dict],
    *,
    name: str,
    max_points: int | None,
) -> list[dict]:
    if max_points is None or max_points <= 0 or len(points) <= max_points:
        return points
    bucket_size = ceil(len(points) / max_points)
    sampled: list[dict] = []
    for index in range(0, len(points), bucket_size):
        bucket = points[index:index + bucket_size]
        if not bucket:
            continue
        if name in STATE_SERIES_NAMES:
            value = bucket[-1]["value"]
        else:
            value = sum(float(item["value"]) for item in bucket) / len(bucket)
        sampled.append(
            {
                "time": bucket[-1]["time"],
                "value": value,
            }
        )
    return sampled


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


def _interval_evaluation_points(
    start: datetime,
    end: datetime,
    interval: str,
) -> list[tuple[datetime, datetime]]:
    if end < start:
        return []
    step = _interval_timedelta(interval)
    bucket_start = _bucket_datetime(start, interval)
    if bucket_start < start:
        bucket_start += step
    points: list[tuple[datetime, datetime]] = []
    while bucket_start <= end:
        evaluation_time = min(bucket_start + step - timedelta(microseconds=1), end)
        points.append((bucket_start, evaluation_time))
        bucket_start += step
    return points


def _overlapping_replay_session_windows(
    start: datetime,
    end: datetime,
) -> list[tuple[datetime, datetime]]:
    if end < start:
        return []
    windows: list[tuple[datetime, datetime]] = []
    trading_day = trading_day_for(start)
    end_trading_day = trading_day_for(end)
    while trading_day <= end_trading_day:
        for window_start, window_end in session_windows_for(trading_day, "day_and_night"):
            if window_end < start or window_start > end:
                continue
            windows.append((window_start, window_end))
        trading_day += timedelta(days=1)
    return windows
