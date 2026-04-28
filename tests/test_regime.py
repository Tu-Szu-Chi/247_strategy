import unittest
from datetime import date, datetime, timedelta

from qt_platform.domain import Bar, CanonicalTick
from qt_platform.regime import MtxRegimeAnalyzer


def _bar(ts: datetime, close: float, session: str = "day") -> Bar:
    return Bar(
        ts=ts,
        trading_day=date(2026, 4, 28),
        symbol="MTX",
        contract_month="202605",
        session=session,
        open=close - 2,
        high=close + 3,
        low=close - 3,
        close=close,
        volume=100.0,
        open_interest=None,
        source="test",
        instrument_key="MTX202605",
    )


def _tick(ts: datetime, direction: str = "up", session: str = "day") -> CanonicalTick:
    return CanonicalTick(
        ts=ts,
        trading_day=date(2026, 4, 28),
        symbol="MTX",
        instrument_key="MTX202605",
        contract_month="202605",
        strike_price=None,
        call_put=None,
        session=session,
        price=20000.0,
        size=1.0,
        tick_direction=direction,
        source="test",
    )


class RegimeAnalyzerTest(unittest.TestCase):
    def test_trade_intensity_ratio_uses_recent_bar_baseline(self) -> None:
        analyzer = MtxRegimeAnalyzer()
        start = datetime(2026, 4, 28, 9, 0, 0)

        for index in range(30):
            bar_ts = start + timedelta(minutes=index)
            analyzer.ingest_bar(_bar(bar_ts, 20000.0 + index))
            tick_count = 20 if index < 25 else 5
            for offset in range(tick_count):
                analyzer.ingest_tick(_tick(bar_ts + timedelta(seconds=offset)))

        snapshot = analyzer.snapshot(start + timedelta(minutes=29, seconds=59))

        self.assertAlmostEqual(snapshot.trade_intensity_ratio_30b, 0.286, places=3)
        self.assertEqual(snapshot.trade_intensity_5b, 25)

    def test_trade_intensity_ratio_stays_inside_same_session(self) -> None:
        analyzer = MtxRegimeAnalyzer()
        night_start = datetime(2026, 4, 28, 15, 0, 0)
        for index in range(8):
            bar_ts = night_start + timedelta(minutes=index)
            analyzer.ingest_bar(_bar(bar_ts, 20100.0 + index, session="night"))
            for offset in range(4):
                analyzer.ingest_tick(_tick(bar_ts + timedelta(seconds=offset), session="night"))

        snapshot = analyzer.snapshot(night_start + timedelta(minutes=7, seconds=59))

        self.assertAlmostEqual(snapshot.trade_intensity_ratio_30b, 1.0, places=3)


if __name__ == "__main__":
    unittest.main()
