from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from qt_platform.domain import Bar
from qt_platform.kronos.features import bar_minutes, infer_bar_interval
from qt_platform.kronos.probability import (
    ProbabilityTarget,
    calculate_probability_metrics,
    max_horizon_steps,
)


class PathPredictor(Protocol):
    def predict_paths(
        self,
        bars: Sequence[Bar],
        *,
        pred_len: int,
        sample_count: int,
        temperature: float = 1.0,
        top_k: int = 0,
        top_p: float = 0.9,
        verbose: bool = False,
    ) -> Any:
        raise NotImplementedError


def build_probability_indicator_series(
    bars: Sequence[Bar],
    *,
    predictor: PathPredictor,
    lookback: int,
    targets: Sequence[ProbabilityTarget],
    sample_count: int,
    temperature: float = 1.0,
    top_k: int = 0,
    top_p: float = 0.9,
    verbose: bool = False,
    stride: int = 1,
    max_decisions: int | None = None,
    decision_start: Any | None = None,
    decision_end: Any | None = None,
) -> dict[str, list[dict[str, Any]]]:
    if lookback <= 0:
        raise ValueError("lookback must be positive")
    if sample_count <= 0:
        raise ValueError("sample_count must be positive")
    if stride <= 0:
        raise ValueError("stride must be positive")
    if max_decisions is not None and max_decisions <= 0:
        raise ValueError("max_decisions must be positive")
    if not targets:
        raise ValueError("at least one probability target is required")
    if len(bars) < lookback:
        return {}

    interval = infer_bar_interval(bars)
    resolved_bar_minutes = bar_minutes(interval)
    pred_len = max_horizon_steps(targets, bar_minutes=resolved_bar_minutes)
    series: dict[str, list[dict[str, Any]]] = {}
    emitted_decisions = 0
    first_decision_index = lookback - 1
    if decision_start is not None:
        for index in range(lookback - 1, len(bars)):
            if bars[index].ts >= decision_start:
                first_decision_index = index
                break
        else:
            return {}

    for end_index in range(first_decision_index, len(bars), stride):
        if max_decisions is not None and emitted_decisions >= max_decisions:
            break
        context_bars = bars[end_index - lookback + 1:end_index + 1]
        decision_bar = bars[end_index]
        if decision_end is not None and decision_bar.ts > decision_end:
            break
        paths = predictor.predict_paths(
            context_bars,
            pred_len=pred_len,
            sample_count=sample_count,
            temperature=temperature,
            top_k=top_k,
            top_p=top_p,
            verbose=verbose,
        )
        metrics = calculate_probability_metrics(
            paths,
            current_close=decision_bar.close,
            targets=targets,
            bar_minutes=resolved_bar_minutes,
        )
        append_metrics_point(series, time=decision_bar.ts, metrics=metrics)
        emitted_decisions += 1

    return series


def append_metrics_point(
    series: dict[str, list[dict[str, Any]]],
    *,
    time: Any,
    metrics: dict[str, float | int],
) -> None:
    point_time = time.isoformat() if hasattr(time, "isoformat") else time
    for name, value in metrics.items():
        series.setdefault(name, []).append({"time": point_time, "value": value})
