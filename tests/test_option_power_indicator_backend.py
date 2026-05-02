import unittest
from datetime import datetime, timedelta
from time import perf_counter

from qt_platform.monitor.indicator_backend import (
    build_indicator_series,
    compute_pressure_metrics,
)


class OptionPowerIndicatorBackendTest(unittest.TestCase):
    def test_compute_pressure_metrics_matches_option_power_aggregator_cases(self) -> None:
        metrics = compute_pressure_metrics(
            contracts=[
                {
                    "contract_month": "202504W2",
                    "strike_price": 18000.0,
                    "call_put": "call",
                    "cumulative_buy_volume": 10,
                    "cumulative_sell_volume": 0,
                },
                {
                    "contract_month": "202504W2",
                    "strike_price": 18100.0,
                    "call_put": "put",
                    "cumulative_buy_volume": 0,
                    "cumulative_sell_volume": 10,
                },
                {
                    "contract_month": "202505",
                    "strike_price": 18200.0,
                    "call_put": "call",
                    "cumulative_buy_volume": 0,
                    "cumulative_sell_volume": 10,
                },
            ],
            underlying_reference_price=18000.0,
        )

        self.assertEqual(
            metrics,
            {
                "raw_pressure": 14,
                "pressure_index": 61,
                "raw_pressure_weighted": 15,
                "pressure_index_weighted": 58,
            },
        )

    def test_build_indicator_series_adds_backend_derived_state_series(self) -> None:
        snapshots = [
            _snapshot(
                pressure_index=-20,
                raw_pressure=-20,
                structure_state=-1,
                chop_score=12,
                regime_label="trend_down",
                cvd_slope=-3,
                choppiness_14=40,
                compression_state="expanding",
            ),
            _snapshot(
                pressure_index=-15,
                raw_pressure=-18,
                structure_state=-1,
                chop_score=31,
                regime_label="trend_down",
                cvd_slope=-4,
                choppiness_14=40,
                compression_state="expanding",
            ),
        ]

        series = build_indicator_series(
            ["2025-04-11T09:00:00", "2025-04-11T09:01:00"],
            snapshots,
        )

        self.assertEqual(series["regime_state"][0]["value"], -1)
        self.assertEqual(series["structure_state"][1]["value"], -1)
        self.assertEqual(series["trend_bias_state"][0]["value"], -1)
        self.assertAlmostEqual(series["trend_quality_score"][0]["value"], 39.0)
        self.assertEqual(series["flow_state"][0]["value"], -1)
        self.assertEqual(series["range_state"][0]["value"], 1)

    def test_build_indicator_series_benchmark_smoke(self) -> None:
        start = datetime(2025, 4, 11, 9, 0, 0)
        snapshot_count = 1_440
        snapshot_times = [
            (start + timedelta(minutes=index)).isoformat()
            for index in range(snapshot_count)
        ]
        snapshots = [
            _snapshot(
                pressure_index=(index % 80) - 40,
                raw_pressure=(index % 120) - 60,
                structure_state=1 if index % 9 < 4 else -1,
                chop_score=index % 35,
                regime_label="trend_up" if index % 9 < 4 else "trend_down",
                cvd_slope=float((index % 13) - 6),
                choppiness_14=35 + (index % 35),
                compression_state="expanding" if index % 5 else "compressed",
            )
            for index in range(snapshot_count)
        ]

        started = perf_counter()
        series = build_indicator_series(snapshot_times, snapshots)
        elapsed = perf_counter() - started

        self.assertEqual(len(series["flow_state"]), snapshot_count)
        self.assertEqual(len(series["trend_quality_score"]), snapshot_count)
        self.assertLess(elapsed, 5.0)


def _snapshot(
    *,
    pressure_index: int,
    raw_pressure: int,
    structure_state: int,
    chop_score: int,
    regime_label: str,
    cvd_slope: float,
    choppiness_14: float,
    compression_state: str,
) -> dict:
    return {
        "pressure_index": pressure_index,
        "raw_pressure": raw_pressure,
        "pressure_index_weighted": pressure_index,
        "raw_pressure_weighted": raw_pressure,
        "structure_state": structure_state,
        "iv_surface": {"skew": 0.25},
        "regime": {
            "regime_label": regime_label,
            "trend_score": 60,
            "chop_score": chop_score,
            "reversal_risk": 10,
            "vwap_distance_bps": -3,
            "directional_efficiency_15b": 0.6,
            "tick_imbalance_5b": -0.5,
            "trade_intensity_ratio_30b": 1.1,
            "range_ratio_5b_30b": 0.8,
            "adx_14": 24,
            "plus_di_14": 10,
            "minus_di_14": 22,
            "di_bias_14": -12,
            "choppiness_14": choppiness_14,
            "compression_score": 10,
            "expansion_score": 70,
            "compression_expansion_state": compression_state,
            "session_cvd": -120,
            "cvd_5b_delta": -20,
            "cvd_15b_delta": -80,
            "cvd_5b_slope": cvd_slope,
            "cvd_price_alignment": "aligned_down",
            "price_cvd_divergence_15b": "none",
        },
    }
