from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import ceil
from typing import Any

try:  # Polars is the target execution engine; keep imports lazy-friendly for old envs.
    import polars as pl
except ModuleNotFoundError:  # pragma: no cover - exercised only before deps are installed
    pl = None  # type: ignore[assignment]


from qt_platform.indicators.catalog import MONITOR_INDICATOR_SERIES_NAMES
from qt_platform.indicators.collection.pressure_logic import (
    compute_pressure_metrics,
    normalized_pressure,
    directional_flow,
    PressureContractInput,
    _coerce_pressure_contract,
    _infer_strike_step,
    _expiry_weights,
    _gaussian_weight,
    SECOND_EXPIRY_WEIGHT,
    PRESSURE_SIGMA,
)

INDICATOR_SERIES_NAMES = list(MONITOR_INDICATOR_SERIES_NAMES)

REGIME_NUMERIC_FIELDS = [
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
    "session_cvd",
    "cvd_5b_delta",
    "cvd_15b_delta",
    "cvd_5b_slope",
]


def compute_pressure_metrics_frame(
    rows: Iterable[Mapping[str, Any]],
    *,
    time_column: str = "time",
) -> Any:
    row_items = list(rows)
    if not row_items:
        if pl is None:
            return []
        return pl.DataFrame(
            schema={
                time_column: pl.String,
                "raw_pressure": pl.Int64,
                "pressure_index": pl.Int64,
                "raw_pressure_weighted": pl.Int64,
                "pressure_index_weighted": pl.Int64,
            }
        )

    if pl is not None:
        frame = pl.DataFrame(row_items)
        groups = frame.partition_by(time_column, as_dict=True)
        output_rows = []
        for key, group in groups.items():
            time_value = key[0] if isinstance(key, tuple) else key
            underlying_reference_price = group["underlying_reference_price"][0]
            metrics = compute_pressure_metrics(
                contracts=group.to_dicts(),
                underlying_reference_price=float(underlying_reference_price)
                if underlying_reference_price is not None
                else None,
            )
            output_rows.append({time_column: time_value, **metrics})
        return pl.DataFrame(output_rows).sort(time_column)

    output_rows = []
    times = sorted({item.get(time_column) for item in row_items})
    for time_value in times:
        group = [item for item in row_items if item.get(time_column) == time_value]
        reference = group[0].get("underlying_reference_price") if group else None
        output_rows.append(
            {
                time_column: time_value,
                **compute_pressure_metrics(
                    contracts=group,
                    underlying_reference_price=float(reference) if reference is not None else None,
                ),
            }
        )
    return output_rows


def build_indicator_series(snapshot_times: Sequence[str], snapshots: Sequence[Mapping[str, Any]]) -> dict[str, list[dict]]:
    rows = [_snapshot_indicator_row(ts, snapshot) for ts, snapshot in zip(snapshot_times, snapshots)]
    if not rows:
        return {name: [] for name in INDICATOR_SERIES_NAMES}

    if pl is not None:
        rows = (
            pl.DataFrame(rows)
            .sort("time")
            .with_columns(
                trend_quality_score=(
                    ((pl.col("adx_14") * 1.4 + (100 - pl.col("choppiness_14"))) / 2.4)
                    .clip(0, 100)
                ),
                trend_bias_state=(
                    pl.when((pl.col("adx_14") >= 18) & (pl.col("di_bias_14") >= 8))
                    .then(1)
                    .when((pl.col("adx_14") >= 18) & (pl.col("di_bias_14") <= -8))
                    .then(-1)
                    .otherwise(0)
                ),
                flow_state=(
                    pl.when(pl.col("price_cvd_divergence_15b") > 0)
                    .then(1)
                    .when(pl.col("price_cvd_divergence_15b") < 0)
                    .then(-1)
                    .otherwise(pl.col("cvd_price_alignment"))
                ),
                range_state=(
                    pl.when(pl.col("compression_expansion_state") < 0)
                    .then(-1)
                    .when(pl.col("compression_expansion_state") > 0)
                    .then(1)
                    .otherwise(0)
                ),
            )
            .to_dicts()
        )
    else:
        rows = sorted(rows, key=lambda item: item["time"])
        for row in rows:
            row["trend_quality_score"] = clamp_number(
                (row["adx_14"] * 1.4 + (100 - row["choppiness_14"])) / 2.4,
                0,
                100,
            )
            row["trend_bias_state"] = trend_bias_state(
                adx_value=row["adx_14"],
                di_bias_value=row["di_bias_14"],
            )
            row["flow_state"] = flow_state(
                cvd_alignment_value=row["cvd_price_alignment"],
                cvd_divergence_value=row["price_cvd_divergence_15b"],
            )
            row["range_state"] = range_state(row["compression_expansion_state"])

    _populate_python_windowed_indicators(rows)

    payload: dict[str, list[dict]] = {name: [] for name in INDICATOR_SERIES_NAMES}
    for row in rows:
        for name in INDICATOR_SERIES_NAMES:
            payload[name].append({"time": row["time"], "value": row.get(name, 0)})
    return payload


def regime_state_value(label: str | None) -> int:
    if label == "trend_up" or label == "reversal_up":
        return 1
    if label == "trend_down" or label == "reversal_down":
        return -1
    return 0


def structure_state_value(
    now: datetime,
    drive_points: Sequence[tuple[datetime, float]],
    expansion_points: Sequence[tuple[datetime, float]],
) -> int:
    cutoff = now - timedelta(minutes=30)
    rolling_drive = [abs(value) for ts, value in drive_points if ts >= cutoff]
    rolling_expansion = [value for ts, value in expansion_points if ts >= cutoff]
    if not rolling_drive or not rolling_expansion:
        return 0

    drive_threshold = max(rolling_quantile(rolling_drive, 0.65), 0.08)
    expansion_threshold = max(rolling_quantile(rolling_expansion, 0.60), 0.12)
    current_drive = drive_points[-1][1]
    current_expansion = expansion_points[-1][1]
    if current_expansion <= expansion_threshold:
        return 0
    if current_drive > drive_threshold:
        return 1
    if current_drive < -drive_threshold:
        return -1
    return 0


def compression_expansion_state_value(state: str | None) -> int:
    if state == "compressed":
        return -1
    if state == "expanding":
        return 1
    if state == "expanded":
        return 2
    return 0


def cvd_price_alignment_value(state: str | None) -> int:
    if state == "aligned_up":
        return 1
    if state == "aligned_down":
        return -1
    if state == "diverged":
        return 2
    return 0


def price_cvd_divergence_value(state: str | None) -> int:
    if state == "bullish":
        return 1
    if state == "bearish":
        return -1
    return 0


def trend_bias_state(*, adx_value: float, di_bias_value: float) -> int:
    if adx_value >= 18 and di_bias_value >= 8:
        return 1
    if adx_value >= 18 and di_bias_value <= -8:
        return -1
    return 0


def flow_state(*, cvd_alignment_value: int, cvd_divergence_value: int) -> int:
    if cvd_divergence_value > 0:
        return 1
    if cvd_divergence_value < 0:
        return -1
    return cvd_alignment_value


def range_state(value: int) -> int:
    if value < 0:
        return -1
    if value > 0:
        return 1
    return 0


def resolve_pressure_side(value: float) -> int:
    if value >= 2:
        return 1
    if value <= -2:
        return -1
    return 0


def rolling_quantile(values: Sequence[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def clamp_number(value: float, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))


def _populate_python_windowed_indicators(rows: list[dict[str, Any]]) -> None:
    drive_points: list[tuple[datetime, float]] = []
    expansion_points: list[tuple[datetime, float]] = []
    sticky_structure_state = 0
    parsed_times = [datetime.fromisoformat(str(row["time"])) for row in rows]

    for index, row in enumerate(rows):
        current_time = parsed_times[index]
        drive_value = float(row.get("directional_efficiency_15b", 0) or 0) * float(row.get("tick_imbalance_5b", 0) or 0)
        expansion_value = float(row.get("range_ratio_5b_30b", 0) or 0)
        drive_points.append((current_time, drive_value))
        expansion_points.append((current_time, expansion_value))
        if "_source_structure_state" in row:
            row["structure_state"] = row["_source_structure_state"]
        else:
            candidate = structure_state_value(current_time, drive_points, expansion_points)
            if candidate != 0:
                sticky_structure_state = candidate
            row["structure_state"] = sticky_structure_state

    for index, row in enumerate(rows):
        slope_history = _rolling_window_values(
            rows=rows,
            parsed_times=parsed_times,
            index=index,
            field="cvd_5b_slope",
            minutes=30,
        )
        slope_threshold = max(rolling_quantile([abs(value) for value in slope_history], 0.8), 1)
        current_slope = float(row.get("cvd_5b_slope", 0) or 0)
        row["flow_impulse_score"] = clamp_number((current_slope / slope_threshold) * 100, -100, 100)


def _rolling_window_values(
    *,
    rows: Sequence[Mapping[str, Any]],
    parsed_times: Sequence[datetime],
    index: int,
    field: str,
    minutes: int,
) -> list[float]:
    now = parsed_times[index]
    cutoff = now - timedelta(minutes=minutes)
    values: list[float] = []
    for item_time, row in zip(parsed_times, rows):
        if item_time < cutoff or item_time > now:
            continue
        values.append(float(row.get(field, 0) or 0))
    return values


def _snapshot_indicator_row(ts: str, snapshot: Mapping[str, Any]) -> dict[str, Any]:
    regime = snapshot.get("regime") or {}
    row: dict[str, Any] = {
        "time": ts,
        "pressure_index": _number(snapshot.get("pressure_index")),
        "raw_pressure": _number(snapshot.get("raw_pressure")),
        "pressure_index_weighted": _number(snapshot.get("pressure_index_weighted")),
        "raw_pressure_weighted": _number(snapshot.get("raw_pressure_weighted")),
        "regime_state": _number(snapshot.get("regime_state"), regime_state_value(regime.get("regime_label"))),
        "compression_expansion_state": _number(
            snapshot.get("compression_expansion_state"),
            compression_expansion_state_value(regime.get("compression_expansion_state")),
        ),
        "cvd_price_alignment": _number(
            snapshot.get("cvd_price_alignment"),
            cvd_price_alignment_value(regime.get("cvd_price_alignment")),
        ),
        "price_cvd_divergence_15b": _number(
            snapshot.get("price_cvd_divergence_15b"),
            price_cvd_divergence_value(regime.get("price_cvd_divergence_15b")),
        ),
        "iv_skew": _iv_surface_value(snapshot, "skew"),
        "trend_quality_score": _number(snapshot.get("trend_quality_score")),
        "structure_state": _number(snapshot.get("structure_state")),
    }
    if "structure_state" in snapshot:
        row["_source_structure_state"] = _number(snapshot.get("structure_state"))
        row["structure_state"] = row["_source_structure_state"]
    else:
        row["structure_state"] = 0

    for name in REGIME_NUMERIC_FIELDS:
        row[name] = _number(snapshot.get(name), _number(regime.get(name)))
    return row


def _iv_surface_value(snapshot: Mapping[str, Any], field: str) -> float:
    value = (snapshot.get("iv_surface") or {}).get(field)
    return float(value) if value is not None else 0.0


def _number(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
