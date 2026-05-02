from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from qt_platform.indicators.catalog import MONITOR_INDICATOR_SERIES_NAMES
from qt_platform.monitor.indicator_backend import build_indicator_series


def materialize_monitor_snapshot(
    snapshot: Mapping[str, Any],
    *,
    kronos_snapshot: Mapping[str, Any] | None = None,
    kronos_metrics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(snapshot)
    generated_at = str(payload.get("generated_at") or "")
    if generated_at:
        series = build_indicator_series([generated_at], [payload])
        for name in MONITOR_INDICATOR_SERIES_NAMES:
            points = series.get(name) or []
            if not points:
                continue
            payload[name] = points[-1]["value"]

    if kronos_snapshot is not None:
        payload["kronos"] = dict(kronos_snapshot)
    if kronos_metrics:
        payload.update(dict(kronos_metrics))
    return payload
