from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import ceil, floor
from typing import Any


KRONOS_FEATURE_NAMES = ("open", "high", "low", "close", "volume", "amount")


@dataclass(frozen=True, order=True)
class ProbabilityTarget:
    minutes: int
    points: float

    def __post_init__(self) -> None:
        if self.minutes <= 0:
            raise ValueError("minutes must be positive")
        if self.points <= 0:
            raise ValueError("points must be positive")

    @property
    def point_label(self) -> str:
        return _number_token(self.points)

    @property
    def minute_label(self) -> str:
        return str(self.minutes)

    def horizon_steps(self, *, bar_minutes: float = 1.0) -> int:
        if bar_minutes <= 0:
            raise ValueError("bar_minutes must be positive")
        return max(1, int(ceil(self.minutes / bar_minutes)))


def parse_probability_target(raw: str) -> ProbabilityTarget:
    value = raw.strip().lower()
    if not value:
        raise ValueError("probability target cannot be empty")
    if ":" not in value:
        raise ValueError("probability target must use '<minutes>m:<points>', for example '10m:50'")
    minutes_raw, points_raw = value.split(":", 1)
    minutes_raw = minutes_raw.removesuffix("m").strip()
    points_raw = points_raw.removesuffix("pt").removesuffix("pts").strip()
    if not minutes_raw or not points_raw:
        raise ValueError("probability target must include both minutes and points")
    return ProbabilityTarget(minutes=int(minutes_raw), points=float(points_raw))


def probability_field_names(target: ProbabilityTarget) -> tuple[str, str]:
    suffix = f"{target.point_label}_in_{target.minute_label}m_probability"
    return f"mtx_up_{suffix}", f"mtx_down_{suffix}"


def calculate_probability_metrics(
    paths: Any,
    *,
    current_close: float,
    targets: Sequence[ProbabilityTarget],
    bar_minutes: float = 1.0,
    feature_names: Sequence[str] = KRONOS_FEATURE_NAMES,
) -> dict[str, float | int]:
    if not targets:
        raise ValueError("at least one probability target is required")
    numpy_metrics = _calculate_probability_metrics_numpy(
        paths,
        current_close=current_close,
        targets=targets,
        bar_minutes=bar_minutes,
        feature_names=feature_names,
    )
    if numpy_metrics is not None:
        return numpy_metrics

    path_rows = _coerce_paths(paths)
    if not path_rows:
        raise ValueError("paths must contain at least one sample")
    pred_len = len(path_rows[0])
    if pred_len <= 0:
        raise ValueError("paths must contain at least one prediction step")

    high_idx = _feature_index(feature_names, "high")
    low_idx = _feature_index(feature_names, "low")
    close_idx = _feature_index(feature_names, "close")
    _validate_paths(path_rows, feature_count=max(high_idx, low_idx, close_idx) + 1)

    metrics: dict[str, float | int] = {
        "mtx_probability_ready": 1,
        "mtx_probability_sample_count": len(path_rows),
    }
    close_delta_horizons: set[int] = set()

    for target in targets:
        horizon_steps = target.horizon_steps(bar_minutes=bar_minutes)
        if horizon_steps > pred_len:
            raise ValueError(
                f"target {target.minutes}m requires {horizon_steps} prediction steps, "
                f"but paths only include {pred_len}"
            )
        up_field, down_field = probability_field_names(target)
        up_count = 0
        down_count = 0
        for sample in path_rows:
            target_rows = sample[:horizon_steps]
            if any(max(row[high_idx], row[low_idx]) >= current_close + target.points for row in target_rows):
                up_count += 1
            if any(min(row[high_idx], row[low_idx]) <= current_close - target.points for row in target_rows):
                down_count += 1
        metrics[up_field] = up_count / len(path_rows)
        metrics[down_field] = down_count / len(path_rows)
        close_delta_horizons.add(horizon_steps)

    for horizon_steps in sorted(close_delta_horizons):
        close_delta = [sample[horizon_steps - 1][close_idx] - current_close for sample in path_rows]
        minutes = _horizon_minutes_label(horizon_steps, bar_minutes)
        metrics[f"mtx_expected_close_delta_{minutes}m"] = sum(close_delta) / len(close_delta)
        metrics[f"mtx_path_close_delta_p10_{minutes}m"] = _percentile(close_delta, 10)
        metrics[f"mtx_path_close_delta_p50_{minutes}m"] = _percentile(close_delta, 50)
        metrics[f"mtx_path_close_delta_p90_{minutes}m"] = _percentile(close_delta, 90)

    return metrics


def _calculate_probability_metrics_numpy(
    paths: Any,
    *,
    current_close: float,
    targets: Sequence[ProbabilityTarget],
    bar_minutes: float,
    feature_names: Sequence[str],
) -> dict[str, float | int] | None:
    np = _optional_numpy()
    if np is None:
        return None
    try:
        path_array = np.asarray(paths, dtype=float)
    except (TypeError, ValueError):
        return None
    if path_array.ndim != 3:
        raise ValueError("paths must have shape (sample_count, pred_len, feature_count)")
    if path_array.shape[0] <= 0:
        raise ValueError("paths must contain at least one sample")
    if path_array.shape[1] <= 0:
        raise ValueError("paths must contain at least one prediction step")

    high_idx = _feature_index(feature_names, "high")
    low_idx = _feature_index(feature_names, "low")
    close_idx = _feature_index(feature_names, "close")
    feature_count = max(high_idx, low_idx, close_idx) + 1
    if path_array.shape[2] < feature_count:
        raise ValueError("path rows do not include all required features")

    metrics: dict[str, float | int] = {
        "mtx_probability_ready": 1,
        "mtx_probability_sample_count": int(path_array.shape[0]),
    }
    close_delta_horizons: set[int] = set()

    for target in targets:
        horizon_steps = target.horizon_steps(bar_minutes=bar_minutes)
        if horizon_steps > path_array.shape[1]:
            raise ValueError(
                f"target {target.minutes}m requires {horizon_steps} prediction steps, "
                f"but paths only include {path_array.shape[1]}"
            )
        target_paths = path_array[:, :horizon_steps, :]
        highs = np.maximum(target_paths[:, :, high_idx], target_paths[:, :, low_idx])
        lows = np.minimum(target_paths[:, :, high_idx], target_paths[:, :, low_idx])
        up_field, down_field = probability_field_names(target)
        metrics[up_field] = float((highs >= current_close + target.points).any(axis=1).mean())
        metrics[down_field] = float((lows <= current_close - target.points).any(axis=1).mean())
        close_delta_horizons.add(horizon_steps)

    for horizon_steps in sorted(close_delta_horizons):
        close_delta = path_array[:, horizon_steps - 1, close_idx] - current_close
        minutes = _horizon_minutes_label(horizon_steps, bar_minutes)
        metrics[f"mtx_expected_close_delta_{minutes}m"] = float(close_delta.mean())
        metrics[f"mtx_path_close_delta_p10_{minutes}m"] = float(np.percentile(close_delta, 10))
        metrics[f"mtx_path_close_delta_p50_{minutes}m"] = float(np.percentile(close_delta, 50))
        metrics[f"mtx_path_close_delta_p90_{minutes}m"] = float(np.percentile(close_delta, 90))

    return metrics


def max_horizon_steps(targets: Sequence[ProbabilityTarget], *, bar_minutes: float = 1.0) -> int:
    if not targets:
        raise ValueError("at least one probability target is required")
    return max(target.horizon_steps(bar_minutes=bar_minutes) for target in targets)


def _feature_index(feature_names: Sequence[str], name: str) -> int:
    try:
        return list(feature_names).index(name)
    except ValueError as exc:
        raise ValueError(f"feature_names must include {name!r}") from exc


def _coerce_paths(paths: Any) -> list[list[list[float]]]:
    if hasattr(paths, "tolist"):
        paths = paths.tolist()
    if not isinstance(paths, Sequence) or isinstance(paths, (str, bytes)):
        raise ValueError("paths must have shape (sample_count, pred_len, feature_count)")
    return [
        [
            [float(value) for value in row]
            for row in sample
        ]
        for sample in paths
    ]


def _validate_paths(paths: list[list[list[float]]], *, feature_count: int) -> None:
    pred_len = len(paths[0])
    for sample in paths:
        if len(sample) != pred_len:
            raise ValueError("all path samples must have the same prediction length")
        for row in sample:
            if len(row) < feature_count:
                raise ValueError("path rows do not include all required features")


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise ValueError("values cannot be empty")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * (percentile / 100)
    lower = floor(position)
    upper = ceil(position)
    if lower == upper:
        return ordered[int(position)]
    lower_weight = upper - position
    upper_weight = position - lower
    return ordered[lower] * lower_weight + ordered[upper] * upper_weight


def _number_token(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}".replace("-", "neg_").replace(".", "_")


def _horizon_minutes_label(horizon_steps: int, bar_minutes: float) -> str:
    minutes = horizon_steps * bar_minutes
    return _number_token(minutes)


def _optional_numpy() -> Any | None:
    try:
        import numpy as np
    except ModuleNotFoundError:
        return None
    return np
