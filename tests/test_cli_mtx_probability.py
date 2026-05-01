import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from qt_platform.cli.main import _build_mtx_probability_series, _parse_probability_targets
from qt_platform.domain import Bar
from qt_platform.kronos.probability import ProbabilityTarget


class MtxProbabilityCliTest(unittest.TestCase):
    def test_default_target_is_10m_50(self) -> None:
        self.assertEqual(_parse_probability_targets(None), [ProbabilityTarget(minutes=10, points=50.0)])

    def test_build_mtx_probability_series_writes_indicator_json(self) -> None:
        start = datetime(2026, 4, 13, 8, 45)
        end = start + timedelta(minutes=2)
        store = MagicMock()
        store.list_bars.return_value = _bars(start, 3)

        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "series.json"
            args = _args(start=start, end=end, output=str(output))

            with patch("qt_platform.cli.main.build_bar_repository", return_value=store), patch(
                "qt_platform.cli.main._build_kronos_path_predictor",
                return_value=FakePredictor(),
            ):
                _build_mtx_probability_series(args, _settings())

            payload = json.loads(output.read_text(encoding="utf-8"))

        store.list_bars.assert_called_once_with(
            timeframe="1m",
            symbol="MTX",
            start=start,
            end=end,
        )
        self.assertEqual(payload["metadata"]["symbol"], "MTX")
        self.assertEqual(payload["metadata"]["targets"], ["1m:1"])
        self.assertEqual(payload["metadata"]["bar_count"], 3)
        self.assertEqual(payload["metadata"]["history_start"], start.isoformat())
        self.assertEqual(payload["metadata"]["lookback"], 2)
        self.assertEqual(payload["metadata"]["stride"], 1)
        self.assertIsNone(payload["metadata"]["max_decisions"])
        self.assertEqual(payload["metadata"]["series_names"], sorted(payload["series"]))
        self.assertEqual(len(payload["series"]["mtx_up_1_in_1m_probability"]), 2)
        self.assertEqual(payload["series"]["mtx_probability_sample_count"][0]["value"], 4)

    def test_build_mtx_probability_series_uses_history_start_for_context_only(self) -> None:
        history_start = datetime(2026, 4, 13, 8, 45)
        decision_start = history_start + timedelta(minutes=3)
        end = history_start + timedelta(minutes=5)
        store = MagicMock()
        store.list_bars.return_value = _bars(history_start, 6)

        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "series.json"
            args = _args(start=decision_start, end=end, output=str(output), history_start=history_start)

            with patch("qt_platform.cli.main.build_bar_repository", return_value=store), patch(
                "qt_platform.cli.main._build_kronos_path_predictor",
                return_value=FakePredictor(),
            ):
                _build_mtx_probability_series(args, _settings())

            payload = json.loads(output.read_text(encoding="utf-8"))

        store.list_bars.assert_called_once_with(
            timeframe="1m",
            symbol="MTX",
            start=history_start,
            end=end,
        )
        self.assertEqual(payload["metadata"]["start"], decision_start.isoformat())
        self.assertEqual(payload["metadata"]["history_start"], history_start.isoformat())
        self.assertEqual(
            [point["time"] for point in payload["series"]["mtx_up_1_in_1m_probability"]],
            [
                decision_start.isoformat(),
                (decision_start + timedelta(minutes=1)).isoformat(),
                (decision_start + timedelta(minutes=2)).isoformat(),
            ],
        )


class FakePredictor:
    def predict_paths(self, bars, *, pred_len, sample_count, temperature=1.0, top_k=0, top_p=0.9, verbose=False):
        current = bars[-1].close
        return [
            [[current, current + 2, current - 1, current + 1, 1, current + 1] for _ in range(pred_len)]
            for _ in range(sample_count)
        ]


def _args(*, start: datetime, end: datetime, output: str, history_start: datetime | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        database_url="sqlite:///tmp/test.db",
        symbol="MTX",
        start=start.isoformat(),
        end=end.isoformat(),
        history_start=history_start.isoformat() if history_start else None,
        timeframe="1m",
        report_dir=None,
        lookback=2,
        stride=1,
        max_decisions=None,
        target=["1m:1"],
        sample_count=4,
        temperature=1.0,
        top_k=0,
        top_p=0.9,
        model="NeoQuasar/Kronos-mini",
        tokenizer="NeoQuasar/Kronos-Tokenizer-2k",
        model_revision=None,
        tokenizer_revision=None,
        device=None,
        max_context=512,
        output=output,
        verbose=False,
    )


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        database=SimpleNamespace(url="sqlite:///tmp/test.db"),
        reporting=SimpleNamespace(output_dir="reports"),
    )


def _bars(start: datetime, count: int) -> list[Bar]:
    return [
        Bar(
            start + timedelta(minutes=index),
            date(2026, 4, 13),
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
