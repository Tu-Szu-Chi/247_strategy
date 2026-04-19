import unittest
from datetime import date, datetime, timedelta

from qt_platform.domain import Bar, CanonicalTick
from qt_platform.option_power.replay import OptionPowerReplayService


class DummyStore:
    def __init__(self, ticks, bars=None):
        self.ticks = ticks
        self.bars = bars or []

    def list_ticks_for_symbols(self, symbols, start, end):
        selected = []
        allowed = set(symbols)
        for tick in self.ticks:
            if tick.symbol not in allowed:
                continue
            if tick.ts < start or tick.ts > end:
                continue
            selected.append(tick)
        return sorted(selected, key=lambda item: (item.ts, item.instrument_key or "", item.price, item.size, item.source))

    def list_bars(self, timeframe, symbol, start, end):
        selected = []
        for bar in self.bars:
            if bar.symbol != symbol:
                continue
            if bar.ts < start or bar.ts > end:
                continue
            selected.append(bar)
        return selected


def _tick(
    *,
    ts: datetime,
    symbol: str,
    price: float,
    size: float,
    instrument_key: str,
    contract_month: str = "",
    strike_price: float | None = None,
    call_put: str | None = None,
    tick_direction: str | None = None,
) -> CanonicalTick:
    return CanonicalTick(
        ts=ts,
        trading_day=date(2026, 4, 16),
        symbol=symbol,
        instrument_key=instrument_key,
        contract_month=contract_month,
        strike_price=strike_price,
        call_put=call_put,
        session="day",
        price=price,
        size=size,
        tick_direction=tick_direction,
        source="stub_replay",
    )


class OptionPowerReplayServiceTest(unittest.TestCase):
    def test_create_session_builds_replay_timeline(self) -> None:
        base_ts = datetime(2026, 4, 16, 9, 0, 0)
        store = DummyStore(
            [
                _tick(
                    ts=base_ts,
                    symbol="MTX",
                    price=19450.0,
                    size=1,
                    instrument_key="MTX202605",
                ),
                _tick(
                    ts=base_ts + timedelta(seconds=1),
                    symbol="TXX",
                    price=120.0,
                    size=10,
                    instrument_key="TXX20260419400C",
                    contract_month="202604",
                    strike_price=19400.0,
                    call_put="call",
                    tick_direction="up",
                ),
                _tick(
                    ts=base_ts + timedelta(seconds=2),
                    symbol="TX4",
                    price=118.0,
                    size=8,
                    instrument_key="TX420260419500P",
                    contract_month="202604",
                    strike_price=19500.0,
                    call_put="put",
                    tick_direction="down",
                ),
            ],
            bars=[
                Bar(
                    ts=base_ts,
                    trading_day=date(2026, 4, 16),
                    symbol="MTX",
                    contract_month="202605",
                    session="day",
                    open=19440.0,
                    high=19460.0,
                    low=19430.0,
                    close=19450.0,
                    volume=1200.0,
                    open_interest=None,
                    source="stub_replay",
                    instrument_key="MTX202605",
                )
            ],
        )
        service = OptionPowerReplayService(
            store=store,
            option_root="AUTO",
            expiry_count=2,
            underlying_symbol="MTX",
            snapshot_interval_seconds=5.0,
        )

        metadata = service.create_session(
            start=base_ts,
            end=base_ts + timedelta(seconds=10),
            set_as_default=True,
        )

        self.assertEqual(metadata["selected_option_roots"], ["TX4", "TXX"])
        self.assertEqual(metadata["snapshot_count"], 3)

        default_snapshot = service.current_snapshot()
        self.assertEqual(default_snapshot["underlying_reference_price"], 19450.0)
        self.assertEqual(default_snapshot["raw_pressure"], 0)
        self.assertEqual(default_snapshot["pressure_index"], 0)

        payload = service.get_snapshot(metadata["session_id"], 1)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["index"], 1)
        self.assertEqual(payload["snapshot"]["raw_pressure"], 18)
        self.assertEqual(payload["snapshot"]["raw_pressure_1m"], 18)

        bars = service.get_bars(metadata["session_id"])
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0]["close"], 19450.0)

        series = service.get_series(metadata["session_id"], ["pressure_index", "pressure_index_1m", "pressure_index_5m"])
        self.assertEqual(sorted(series.keys()), ["pressure_index", "pressure_index_1m", "pressure_index_5m"])
        self.assertEqual(len(series["pressure_index"]), 3)
        self.assertEqual(series["pressure_index_5m"][1]["value"], 100)

        snapshot_at = service.get_snapshot_at(metadata["session_id"], base_ts + timedelta(seconds=6))
        self.assertIsNotNone(snapshot_at)
        self.assertEqual(snapshot_at["index"], 1)


if __name__ == "__main__":
    unittest.main()
