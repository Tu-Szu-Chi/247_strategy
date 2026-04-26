from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from math import copysign

from qt_platform.domain import Bar, CanonicalTick


@dataclass(frozen=True)
class RegimeFeatureSnapshot:
    generated_at: str
    session: str
    close: float | None
    session_vwap: float | None
    vwap_distance_bps: float
    directional_efficiency_15m: float
    vwap_cross_count_15m: int
    tick_imbalance_5m: float
    trade_intensity_5m: int
    trade_intensity_ratio_30m: float
    range_ratio_5m_30m: float
    trend_score: int
    chop_score: int
    reversal_risk: int
    regime_label: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RegimeSchemaField:
    name: str
    dtype: str
    description: str
    interpretation: str

    def to_dict(self) -> dict:
        return asdict(self)


REGIME_SCHEMA: tuple[RegimeSchemaField, ...] = (
    RegimeSchemaField(
        name="generated_at",
        dtype="datetime",
        description="這個 feature snapshot 對應的 replay / live 時間點。",
        interpretation="所有欄位都表示此時此刻可觀察到的盤勢狀態。",
    ),
    RegimeSchemaField(
        name="session",
        dtype="string",
        description="day 或 night，盤勢計算必須在同一盤別內進行。",
        interpretation="日盤與夜盤不直接共用累積狀態。",
    ),
    RegimeSchemaField(
        name="close",
        dtype="float|null",
        description="最新可用的 MTX 1 分 K 收盤價。",
        interpretation="作為所有價格特徵的當前參考點。",
    ),
    RegimeSchemaField(
        name="session_vwap",
        dtype="float|null",
        description="同一盤別從開盤到目前為止的成交量加權平均價。",
        interpretation="價格長時間偏離 VWAP 且不反覆穿越時，通常較有趨勢性。",
    ),
    RegimeSchemaField(
        name="vwap_distance_bps",
        dtype="float",
        description="目前 close 與 session VWAP 的距離，單位是 basis points。",
        interpretation="絕對值越大，代表價格越明顯離開平均成本區。",
    ),
    RegimeSchemaField(
        name="directional_efficiency_15m",
        dtype="float",
        description="最近 15 分鐘淨位移，除以同區間高低總 range。",
        interpretation="越接近 1 越像單邊推進，越接近 0 越像來回拉扯。",
    ),
    RegimeSchemaField(
        name="vwap_cross_count_15m",
        dtype="int",
        description="最近 15 分鐘 close 上下穿越 session VWAP 的次數。",
        interpretation="次數越多，通常越偏盤整或糾結。",
    ),
    RegimeSchemaField(
        name="tick_imbalance_5m",
        dtype="float",
        description="最近 5 分鐘以 tick_direction 拆出的主動買賣不平衡。",
        interpretation="接近 +1 偏多方主動，接近 -1 偏空方主動，接近 0 代表拉扯。",
    ),
    RegimeSchemaField(
        name="trade_intensity_5m",
        dtype="int",
        description="最近 5 分鐘成交 tick 筆數。",
        interpretation="數值變大代表市場活化，但仍需搭配方向性一起解讀。",
    ),
    RegimeSchemaField(
        name="trade_intensity_ratio_30m",
        dtype="float",
        description="最近 5 分鐘 tick 筆數，相對於最近 30 分鐘基準密度的比值。",
        interpretation="大於 1 代表近期成交節奏加速，小於 1 代表降溫。",
    ),
    RegimeSchemaField(
        name="range_ratio_5m_30m",
        dtype="float",
        description="最近 5 分鐘 price range 相對於最近 30 分鐘總 range 的占比。",
        interpretation="越大代表短時間內價格開始擴張，可能正在發動。",
    ),
    RegimeSchemaField(
        name="trend_score",
        dtype="int",
        description="綜合效率、VWAP 偏離、tick imbalance、成交節奏後的 0~100 趨勢分數。",
        interpretation="越高越適合視為趨勢延續候選盤，而不是盤整盤。",
    ),
    RegimeSchemaField(
        name="chop_score",
        dtype="int",
        description="綜合低效率、頻繁穿越 VWAP、低偏離與低不平衡後的 0~100 盤整分數。",
        interpretation="越高越代表不適合積極追價，應更保守。",
    ),
    RegimeSchemaField(
        name="reversal_risk",
        dtype="int",
        description="目前主要方向與短線 tick flow 是否衝突的 0~100 反轉風險分數。",
        interpretation="越高越要小心原本趨勢已鈍化或正在反手。",
    ),
    RegimeSchemaField(
        name="regime_label",
        dtype="string",
        description="用 trend_score / chop_score / reversal_risk 粗分出的盤勢標籤。",
        interpretation="第一版只作研究用途，不視為交易黑盒決策。",
    ),
)


@dataclass(frozen=True)
class _BarState:
    ts: datetime
    session: str
    close: float
    high: float
    low: float
    volume: float
    session_vwap: float | None


@dataclass(frozen=True)
class _TickState:
    ts: datetime
    session: str
    signed_size: float
    direction: int


class MtxRegimeAnalyzer:
    def __init__(self) -> None:
        self._session = "unknown"
        self._cum_pv = 0.0
        self._cum_volume = 0.0
        self._bars: deque[_BarState] = deque()
        self._ticks: deque[_TickState] = deque()

    def ingest_bar(self, bar: Bar) -> None:
        if bar.session not in {"day", "night"}:
            return
        self._reset_if_session_changed(bar.session)
        self._cum_pv += bar.close * bar.volume
        self._cum_volume += bar.volume
        self._bars.append(
            _BarState(
                ts=bar.ts,
                session=bar.session,
                close=bar.close,
                high=bar.high,
                low=bar.low,
                volume=bar.volume,
                session_vwap=self._cum_pv / self._cum_volume if self._cum_volume > 0 else None,
            )
        )
        self._evict_old(bar.ts)

    def ingest_tick(self, tick: CanonicalTick) -> None:
        if tick.session not in {"day", "night"}:
            return
        self._reset_if_session_changed(tick.session)
        direction = 1 if tick.tick_direction == "up" else -1 if tick.tick_direction == "down" else 0
        signed_size = float(tick.size) * direction
        self._ticks.append(
            _TickState(
                ts=tick.ts,
                session=tick.session,
                signed_size=signed_size,
                direction=direction,
            )
        )
        self._evict_old(tick.ts)

    def snapshot(self, now: datetime) -> RegimeFeatureSnapshot:
        self._evict_old(now)
        latest_bar = self._bars[-1] if self._bars else None
        if latest_bar is None:
            return RegimeFeatureSnapshot(
                generated_at=now.isoformat(),
                session=self._session,
                close=None,
                session_vwap=None,
                vwap_distance_bps=0.0,
                directional_efficiency_15m=0.0,
                vwap_cross_count_15m=0,
                tick_imbalance_5m=0.0,
                trade_intensity_5m=0,
                trade_intensity_ratio_30m=0.0,
                range_ratio_5m_30m=0.0,
                trend_score=0,
                chop_score=0,
                reversal_risk=0,
                regime_label="no_data",
            )

        bars_15m = self._bars_since(now - timedelta(minutes=15))
        bars_5m = self._bars_since(now - timedelta(minutes=5))
        bars_30m = self._bars_since(now - timedelta(minutes=30))
        ticks_5m = self._ticks_since(now - timedelta(minutes=5))
        ticks_30m = self._ticks_since(now - timedelta(minutes=30))

        session_vwap = latest_bar.session_vwap
        close = latest_bar.close
        vwap_distance_bps = 0.0
        if session_vwap and session_vwap != 0:
            vwap_distance_bps = ((close - session_vwap) / session_vwap) * 10000.0

        directional_efficiency_15m = _directional_efficiency(bars_15m)
        vwap_cross_count_15m = _vwap_cross_count(bars_15m)
        tick_imbalance_5m = _tick_imbalance(ticks_5m)
        trade_intensity_5m = len(ticks_5m)
        trade_intensity_ratio_30m = _trade_intensity_ratio(ticks_5m, ticks_30m)
        range_ratio_5m_30m = _range_ratio(bars_5m, bars_30m)

        trend_score = _trend_score(
            directional_efficiency_15m=directional_efficiency_15m,
            vwap_distance_bps=vwap_distance_bps,
            vwap_cross_count_15m=vwap_cross_count_15m,
            tick_imbalance_5m=tick_imbalance_5m,
            trade_intensity_ratio_30m=trade_intensity_ratio_30m,
            range_ratio_5m_30m=range_ratio_5m_30m,
        )
        chop_score = _chop_score(
            directional_efficiency_15m=directional_efficiency_15m,
            vwap_distance_bps=vwap_distance_bps,
            vwap_cross_count_15m=vwap_cross_count_15m,
            tick_imbalance_5m=tick_imbalance_5m,
            range_ratio_5m_30m=range_ratio_5m_30m,
        )
        reversal_risk = _reversal_risk(
            close=close,
            session_vwap=session_vwap,
            bars_5m=bars_5m,
            bars_15m=bars_15m,
            tick_imbalance_5m=tick_imbalance_5m,
            vwap_cross_count_15m=vwap_cross_count_15m,
        )

        return RegimeFeatureSnapshot(
            generated_at=now.isoformat(),
            session=self._session,
            close=close,
            session_vwap=session_vwap,
            vwap_distance_bps=round(vwap_distance_bps, 3),
            directional_efficiency_15m=round(directional_efficiency_15m, 4),
            vwap_cross_count_15m=vwap_cross_count_15m,
            tick_imbalance_5m=round(tick_imbalance_5m, 4),
            trade_intensity_5m=trade_intensity_5m,
            trade_intensity_ratio_30m=round(trade_intensity_ratio_30m, 3),
            range_ratio_5m_30m=round(range_ratio_5m_30m, 4),
            trend_score=trend_score,
            chop_score=chop_score,
            reversal_risk=reversal_risk,
            regime_label=_regime_label(
                trend_score=trend_score,
                chop_score=chop_score,
                reversal_risk=reversal_risk,
                vwap_distance_bps=vwap_distance_bps,
                tick_imbalance_5m=tick_imbalance_5m,
            ),
        )

    def _reset_if_session_changed(self, session: str) -> None:
        if self._session == session:
            return
        self._session = session
        self._cum_pv = 0.0
        self._cum_volume = 0.0
        self._bars.clear()
        self._ticks.clear()

    def _evict_old(self, now: datetime) -> None:
        cutoff = now - timedelta(minutes=30)
        while self._bars and self._bars[0].ts < cutoff:
            self._bars.popleft()
        while self._ticks and self._ticks[0].ts < cutoff:
            self._ticks.popleft()

    def _bars_since(self, cutoff: datetime) -> list[_BarState]:
        return [bar for bar in self._bars if bar.ts >= cutoff]

    def _ticks_since(self, cutoff: datetime) -> list[_TickState]:
        return [tick for tick in self._ticks if tick.ts >= cutoff]


def regime_schema_dicts() -> list[dict]:
    return [field.to_dict() for field in REGIME_SCHEMA]


def _directional_efficiency(bars: list[_BarState]) -> float:
    if len(bars) < 2:
        return 0.0
    move = abs(bars[-1].close - bars[0].close)
    total_range = max(bar.high for bar in bars) - min(bar.low for bar in bars)
    if total_range <= 0:
        return 0.0
    return _clamp(move / total_range)


def _vwap_cross_count(bars: list[_BarState]) -> int:
    last_sign = 0
    count = 0
    for bar in bars:
        if bar.session_vwap is None:
            continue
        diff = bar.close - bar.session_vwap
        sign = 0 if abs(diff) < 1e-9 else (1 if diff > 0 else -1)
        if sign == 0:
            continue
        if last_sign != 0 and sign != last_sign:
            count += 1
        last_sign = sign
    return count


def _tick_imbalance(ticks: list[_TickState]) -> float:
    if not ticks:
        return 0.0
    up = sum(1 for tick in ticks if tick.direction > 0)
    down = sum(1 for tick in ticks if tick.direction < 0)
    total = up + down
    if total <= 0:
        return 0.0
    return (up - down) / total


def _trade_intensity_ratio(ticks_5m: list[_TickState], ticks_30m: list[_TickState]) -> float:
    if not ticks_5m or not ticks_30m:
        return 0.0
    baseline = len(ticks_30m) / 6.0
    if baseline <= 0:
        return 0.0
    return len(ticks_5m) / baseline


def _range_ratio(short_bars: list[_BarState], long_bars: list[_BarState]) -> float:
    if not short_bars or not long_bars:
        return 0.0
    short_range = max(bar.high for bar in short_bars) - min(bar.low for bar in short_bars)
    long_range = max(bar.high for bar in long_bars) - min(bar.low for bar in long_bars)
    if long_range <= 0:
        return 0.0
    return _clamp(short_range / long_range)


def _trend_score(
    *,
    directional_efficiency_15m: float,
    vwap_distance_bps: float,
    vwap_cross_count_15m: int,
    tick_imbalance_5m: float,
    trade_intensity_ratio_30m: float,
    range_ratio_5m_30m: float,
) -> int:
    vwap_component = _clamp(abs(vwap_distance_bps) / 25.0)
    cross_component = 1.0 - _clamp(vwap_cross_count_15m / 4.0)
    imbalance_component = _clamp(abs(tick_imbalance_5m))
    intensity_component = _clamp(trade_intensity_ratio_30m / 2.0)
    raw = (
        directional_efficiency_15m * 0.32
        + vwap_component * 0.18
        + cross_component * 0.16
        + imbalance_component * 0.16
        + intensity_component * 0.08
        + range_ratio_5m_30m * 0.10
    )
    return round(_clamp(raw) * 100)


def _chop_score(
    *,
    directional_efficiency_15m: float,
    vwap_distance_bps: float,
    vwap_cross_count_15m: int,
    tick_imbalance_5m: float,
    range_ratio_5m_30m: float,
) -> int:
    quiet_vwap = 1.0 - _clamp(abs(vwap_distance_bps) / 20.0)
    cross_component = _clamp(vwap_cross_count_15m / 4.0)
    raw = (
        (1.0 - directional_efficiency_15m) * 0.34
        + quiet_vwap * 0.22
        + cross_component * 0.22
        + (1.0 - _clamp(abs(tick_imbalance_5m))) * 0.12
        + (1.0 - range_ratio_5m_30m) * 0.10
    )
    return round(_clamp(raw) * 100)


def _reversal_risk(
    *,
    close: float,
    session_vwap: float | None,
    bars_5m: list[_BarState],
    bars_15m: list[_BarState],
    tick_imbalance_5m: float,
    vwap_cross_count_15m: int,
) -> int:
    if len(bars_15m) < 2:
        return 0
    medium_move = close - bars_15m[0].close
    short_move = close - bars_5m[0].close if bars_5m else 0.0
    medium_direction = _signed_direction(medium_move)
    short_direction = _signed_direction(short_move)
    micro_direction = _signed_direction(tick_imbalance_5m)
    vwap_direction = 0 if session_vwap is None else _signed_direction(close - session_vwap)

    conflict = 0.0
    if medium_direction != 0 and micro_direction != 0 and medium_direction != micro_direction:
        conflict += 0.55
    if medium_direction != 0 and short_direction != 0 and medium_direction != short_direction:
        conflict += 0.20
    if vwap_direction != 0 and micro_direction != 0 and vwap_direction != micro_direction:
        conflict += 0.15
    conflict += min(vwap_cross_count_15m / 6.0, 1.0) * 0.10
    return round(_clamp(conflict) * 100)


def _regime_label(
    *,
    trend_score: int,
    chop_score: int,
    reversal_risk: int,
    vwap_distance_bps: float,
    tick_imbalance_5m: float,
) -> str:
    direction = _directional_bias(vwap_distance_bps=vwap_distance_bps, tick_imbalance_5m=tick_imbalance_5m)
    if trend_score >= 65 and reversal_risk < 55 and chop_score < 55:
        if direction > 0:
            return "trend_up"
        if direction < 0:
            return "trend_down"
        return "transition"
    if reversal_risk >= 60:
        if direction > 0:
            return "reversal_up"
        if direction < 0:
            return "reversal_down"
        return "transition"
    if chop_score >= 60:
        return "chop"
    return "transition"


def _directional_bias(*, vwap_distance_bps: float, tick_imbalance_5m: float) -> int:
    if vwap_distance_bps >= 3 or tick_imbalance_5m >= 0.08:
        return 1
    if vwap_distance_bps <= -3 or tick_imbalance_5m <= -0.08:
        return -1
    return 0


def _signed_direction(value: float) -> int:
    if abs(value) < 1e-9:
        return 0
    return int(copysign(1, value))


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(value, upper))
