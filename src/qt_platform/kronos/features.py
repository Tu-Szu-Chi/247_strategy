from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from qt_platform.domain import Bar


def bars_to_kronos_frame(bars: Sequence[Bar]) -> Any:
    pd = _require_pandas()
    if not bars:
        raise ValueError("bars cannot be empty")
    rows = []
    for bar in bars:
        average_price = (bar.open + bar.high + bar.low + bar.close) / 4
        rows.append(
            {
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "amount": bar.volume * average_price,
            }
        )
    return pd.DataFrame(rows)


def bar_timestamps(bars: Sequence[Bar]) -> Any:
    pd = _require_pandas()
    if not bars:
        raise ValueError("bars cannot be empty")
    return pd.Series([bar.ts for bar in bars])


def future_timestamps(
    bars: Sequence[Bar],
    *,
    pred_len: int,
    step: timedelta | None = None,
) -> Any:
    pd = _require_pandas()
    if not bars:
        raise ValueError("bars cannot be empty")
    if pred_len <= 0:
        raise ValueError("pred_len must be positive")
    resolved_step = step or infer_bar_interval(bars)
    start = bars[-1].ts + resolved_step
    return pd.Series([start + resolved_step * index for index in range(pred_len)])


def infer_bar_interval(bars: Sequence[Bar], *, default: timedelta = timedelta(minutes=1)) -> timedelta:
    if len(bars) < 2:
        return default
    interval = bars[-1].ts - bars[-2].ts
    if interval.total_seconds() <= 0:
        return default
    return interval


def bar_minutes(interval: timedelta) -> float:
    minutes = interval.total_seconds() / 60
    if minutes <= 0:
        raise ValueError("bar interval must be positive")
    return minutes


def _require_pandas() -> Any:
    try:
        import pandas as pd
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised only before kronos deps are installed
        raise RuntimeError("pandas is required for Kronos feature conversion.") from exc
    return pd
