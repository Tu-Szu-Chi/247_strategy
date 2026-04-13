import unittest
from datetime import datetime

from qt_platform.domain import Bar
from qt_platform.features import compute_minute_force_features


class MinuteForceFeaturesTest(unittest.TestCase):
    def test_compute_force_features_with_ticks(self) -> None:
        bar = Bar(
            ts=datetime(2025, 4, 11, 9, 1),
            trading_day=datetime(2025, 4, 11).date(),
            symbol="2330",
            contract_month="",
            session="day",
            open=848,
            high=848,
            low=840,
            close=842,
            volume=9801,
            open_interest=None,
            source="broker_csv",
            up_ticks=178,
            down_ticks=176,
        )

        features = compute_minute_force_features(bar)

        self.assertEqual(features.tick_total, 354)
        self.assertEqual(features.net_tick_count, 2)
        self.assertAlmostEqual(features.tick_bias_ratio, 2 / 354)
        self.assertAlmostEqual(features.volume_per_tick, 9801 / 354)
        self.assertAlmostEqual(features.force_score, (2 / 354) * 9801)

    def test_compute_force_features_without_ticks(self) -> None:
        bar = Bar(
            ts=datetime(2025, 4, 11, 9, 1),
            trading_day=datetime(2025, 4, 11).date(),
            symbol="TWOTC",
            contract_month="",
            session="day",
            open=200.39,
            high=200.39,
            low=195.88,
            close=195.88,
            volume=368578,
            open_interest=None,
            source="broker_csv",
            up_ticks=None,
            down_ticks=None,
        )

        features = compute_minute_force_features(bar)

        self.assertEqual(features.tick_total, 0)
        self.assertEqual(features.net_tick_count, 0)
        self.assertEqual(features.tick_bias_ratio, 0.0)
        self.assertIsNone(features.volume_per_tick)
        self.assertEqual(features.force_score, 0.0)


if __name__ == "__main__":
    unittest.main()
