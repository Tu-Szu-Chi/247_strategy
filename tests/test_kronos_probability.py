import unittest
from datetime import datetime, timedelta

from qt_platform.domain import Bar
from qt_platform.kronos.probability import (
    ProbabilityTarget,
    calculate_probability_metrics,
    parse_probability_target,
    probability_field_names,
)
from qt_platform.kronos.series import build_probability_indicator_series


class KronosProbabilityTest(unittest.TestCase):
    def test_parse_probability_target(self) -> None:
        self.assertEqual(parse_probability_target("10m:50"), ProbabilityTarget(minutes=10, points=50.0))
        self.assertEqual(parse_probability_target("30:100pt"), ProbabilityTarget(minutes=30, points=100.0))
        self.assertEqual(
            probability_field_names(ProbabilityTarget(minutes=10, points=12.5)),
            ("mtx_up_12_5_in_10m_probability", "mtx_down_12_5_in_10m_probability"),
        )

    def test_calculates_up_down_hit_probabilities_from_raw_paths(self) -> None:
        paths = [
            _path(high=106, low=99, close=101),
            _path(high=104, low=94, close=98),
            _path(high=110, low=90, close=100),
            _path(high=103, low=97, close=102),
        ]

        metrics = calculate_probability_metrics(
            paths,
            current_close=100,
            targets=[ProbabilityTarget(minutes=10, points=5)],
        )

        self.assertEqual(metrics["mtx_probability_ready"], 1)
        self.assertEqual(metrics["mtx_probability_sample_count"], 4)
        self.assertEqual(metrics["mtx_up_5_in_10m_probability"], 0.5)
        self.assertEqual(metrics["mtx_down_5_in_10m_probability"], 0.5)
        self.assertAlmostEqual(metrics["mtx_expected_close_delta_10m"], 0.25)
        self.assertIn("mtx_path_close_delta_p50_10m", metrics)

    def test_series_builder_uses_max_target_horizon_and_predictor_protocol(self) -> None:
        start = datetime(2026, 4, 16, 8, 45)
        bars = _bars(start, 4)
        predictor = FakePredictor()

        series = build_probability_indicator_series(
            bars,
            predictor=predictor,
            lookback=2,
            targets=[
                ProbabilityTarget(minutes=1, points=1),
                ProbabilityTarget(minutes=3, points=2),
            ],
            sample_count=4,
        )

        self.assertEqual(predictor.pred_lens, [3, 3, 3])
        self.assertEqual(len(series["mtx_up_1_in_1m_probability"]), 3)
        self.assertEqual(series["mtx_probability_sample_count"][0]["value"], 4)
        self.assertEqual(series["mtx_up_2_in_3m_probability"][0]["time"], (start + timedelta(minutes=1)).isoformat())

    def test_series_builder_can_stride_and_limit_decisions(self) -> None:
        start = datetime(2026, 4, 16, 8, 45)
        bars = _bars(start, 8)
        predictor = FakePredictor()

        series = build_probability_indicator_series(
            bars,
            predictor=predictor,
            lookback=2,
            targets=[ProbabilityTarget(minutes=1, points=1)],
            sample_count=2,
            stride=2,
            max_decisions=2,
        )

        self.assertEqual(predictor.pred_lens, [1, 1])
        self.assertEqual(
            [point["time"] for point in series["mtx_up_1_in_1m_probability"]],
            [
                (start + timedelta(minutes=1)).isoformat(),
                (start + timedelta(minutes=3)).isoformat(),
            ],
        )

    def test_series_builder_filters_decision_window_after_history_context(self) -> None:
        start = datetime(2026, 4, 16, 8, 45)
        bars = _bars(start, 6)
        predictor = FakePredictor()

        series = build_probability_indicator_series(
            bars,
            predictor=predictor,
            lookback=3,
            targets=[ProbabilityTarget(minutes=1, points=1)],
            sample_count=2,
            decision_start=start + timedelta(minutes=3),
            decision_end=start + timedelta(minutes=5),
            stride=2,
        )

        self.assertEqual(predictor.pred_lens, [1, 1])
        self.assertEqual(
            [point["time"] for point in series["mtx_up_1_in_1m_probability"]],
            [
                (start + timedelta(minutes=3)).isoformat(),
                (start + timedelta(minutes=5)).isoformat(),
            ],
        )

    def test_series_builder_can_skip_diagnostic_series(self) -> None:
        start = datetime(2026, 4, 16, 8, 45)
        bars = _bars(start, 4)
        predictor = FakePredictor()

        series = build_probability_indicator_series(
            bars,
            predictor=predictor,
            lookback=2,
            targets=[ProbabilityTarget(minutes=1, points=1)],
            sample_count=2,
            include_status_metrics=False,
            include_sample_count=False,
            include_path_delta_percentiles=False,
        )

        self.assertIn("mtx_up_1_in_1m_probability", series)
        self.assertIn("mtx_down_1_in_1m_probability", series)
        self.assertIn("mtx_expected_close_delta_1m", series)
        self.assertNotIn("mtx_probability_ready", series)
        self.assertNotIn("mtx_probability_sample_count", series)
        self.assertNotIn("mtx_path_close_delta_p50_1m", series)

    def test_calculate_probability_metrics_can_skip_diagnostic_outputs(self) -> None:
        paths = [
            _path(high=106, low=99, close=101),
            _path(high=104, low=94, close=98),
        ]

        metrics = calculate_probability_metrics(
            paths,
            current_close=100,
            targets=[ProbabilityTarget(minutes=10, points=5)],
            include_status_metrics=False,
            include_sample_count=False,
            include_path_delta_percentiles=False,
        )

        self.assertNotIn("mtx_probability_ready", metrics)
        self.assertNotIn("mtx_probability_sample_count", metrics)
        self.assertNotIn("mtx_path_close_delta_p50_10m", metrics)
        self.assertIn("mtx_up_5_in_10m_probability", metrics)
        self.assertIn("mtx_down_5_in_10m_probability", metrics)
        self.assertIn("mtx_expected_close_delta_10m", metrics)


class FakePredictor:
    def __init__(self) -> None:
        self.pred_lens: list[int] = []

    def predict_paths(self, bars, *, pred_len, sample_count, temperature=1.0, top_k=0, top_p=0.9, verbose=False):
        self.pred_lens.append(pred_len)
        current = bars[-1].close
        paths = []
        for sample in range(sample_count):
            rows = []
            for step in range(pred_len):
                close = current + sample - step
                rows.append([close, close + 1, close - 1, close, 1, close])
            paths.append(rows)
        return paths


def _path(*, high: float, low: float, close: float) -> list[list[float]]:
    return [[100, high, low, close, 1, close] for _ in range(10)]


def _bars(start: datetime, count: int) -> list[Bar]:
    return [
        Bar(
            start + timedelta(minutes=index),
            start.date(),
            "MTX",
            "202604",
            "day",
            100 + index,
            101 + index,
            99 + index,
            100 + index,
            10,
            None,
            "test",
        )
        for index in range(count)
    ]


if __name__ == "__main__":
    unittest.main()
