import unittest
from datetime import datetime, timedelta

from qt_platform.session import iter_expected_bar_timestamps, next_session_start, trading_day_for


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

    def test_next_session_start_after_day_session_returns_night_open(self) -> None:
        self.assertEqual(
            next_session_start(datetime(2024, 1, 1, 13, 46), "day_and_night"),
            datetime(2024, 1, 1, 15, 0),
        )

    def test_next_session_start_after_night_session_returns_next_day_open(self) -> None:
        self.assertEqual(
            next_session_start(datetime(2024, 1, 2, 5, 1), "day_and_night"),
            datetime(2024, 1, 2, 8, 45),
        )


if __name__ == "__main__":
    unittest.main()
