import unittest
from dataclasses import dataclass
from datetime import datetime

from qt_platform.live.shioaji_provider import _nearest_expiry_dates


@dataclass
class _Contract:
    delivery_date: str


class ShioajiOptionUniverseTest(unittest.TestCase):
    def test_nearest_expiry_dates_includes_today_during_day_session(self) -> None:
        contracts = [
            _Contract(delivery_date="2026/04/15"),
            _Contract(delivery_date="2026/04/22"),
            _Contract(delivery_date="2026/05/20"),
        ]
        expiries = _nearest_expiry_dates(
            contracts,
            expiry_count=2,
            now=datetime(2026, 4, 15, 10, 0, 0),
        )
        self.assertEqual([expiry.isoformat() for expiry in expiries], ["2026-04-15", "2026-04-22"])

    def test_nearest_expiry_dates_excludes_today_during_night_session(self) -> None:
        contracts = [
            _Contract(delivery_date="2026/04/15"),
            _Contract(delivery_date="2026/04/22"),
            _Contract(delivery_date="2026/05/20"),
        ]
        expiries = _nearest_expiry_dates(
            contracts,
            expiry_count=2,
            now=datetime(2026, 4, 15, 20, 30, 0),
        )
        self.assertEqual([expiry.isoformat() for expiry in expiries], ["2026-04-22", "2026-05-20"])


if __name__ == "__main__":
    unittest.main()
