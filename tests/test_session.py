import unittest
from datetime import datetime, timedelta

from qt_platform.session import iter_expected_bar_timestamps, trading_day_for


class SessionTest(unittest.TestCase):
    def test_trading_day_for_night_session_after_midnight(self) -> None:
        self.assertEqual(trading_day_for(datetime(2024, 1, 2, 0, 1)).isoformat(), "2024-01-01")

    def test_iter_expected_bar_timestamps_skips_non_trading_break(self) -> None:
        rows = iter_expected_bar_timestamps(
            datetime(2024, 1, 1, 13, 45),
            datetime(2024, 1, 1, 15, 0),
            timedelta(minutes=1),
            "day_and_night",
        )
        self.assertEqual(rows, [datetime(2024, 1, 1, 13, 45), datetime(2024, 1, 1, 15, 0)])


if __name__ == "__main__":
    unittest.main()
