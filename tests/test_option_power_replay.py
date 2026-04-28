import unittest
from datetime import date, datetime, timedelta

from qt_platform.domain import Bar, CanonicalTick
from qt_platform.option_power.replay import OptionPowerReplayService


class DummyStore:
    def __init__(self, ticks, bars=None):
        self.ticks = ticks
        self.bars = bars or []
        self.list_ticks_for_symbols_calls = 0
        self.list_bars_calls = 0

    def list_ticks_for_symbols(self, symbols, start, end):
        self.list_ticks_for_symbols_calls += 1
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
        self.list_bars_calls += 1
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
                ),
                Bar(
                    ts=base_ts,
                    trading_day=date(2026, 4, 16),
                    symbol="TWII",
                    contract_month="",
                    session="day",
                    open=19380.0,
                    high=19410.0,
                    low=19370.0,
                    close=19400.0,
                    volume=0.0,
                    open_interest=None,
                    source="stub_replay",
                    instrument_key="index:TWII",
                    build_source="live_snapshot_agg",
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
        self.assertIn("regime_schema", metadata)
        self.assertTrue(any(field["name"] == "trend_score" for field in metadata["regime_schema"]))
        self.assertIn("regime_state", metadata["available_series"])
        self.assertIn("structure_state", metadata["available_series"])
        self.assertIn("adx_14", metadata["available_series"])
        self.assertIn("session_cvd", metadata["available_series"])
        self.assertIn("compression_score", metadata["available_series"])
        self.assertIn("iv_skew", metadata["available_series"])

        default_snapshot = service.current_snapshot()
        self.assertEqual(default_snapshot["underlying_reference_price"], 19400.0)
        self.assertEqual(default_snapshot["underlying_reference_source"], "twii")
        self.assertEqual(default_snapshot["raw_pressure"], 0)
        self.assertEqual(default_snapshot["pressure_index"], 0)
        self.assertEqual(default_snapshot["raw_pressure_weighted"], 0)
        self.assertEqual(default_snapshot["pressure_index_weighted"], 0)
        self.assertIn("regime", default_snapshot)
        self.assertIn("regime_label", default_snapshot["regime"])

        payload = service.get_snapshot(metadata["session_id"], 1)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["index"], 1)
        self.assertEqual(payload["snapshot"]["raw_pressure"], 17)
        self.assertEqual(payload["snapshot"]["raw_pressure_weighted"], 18)
        self.assertIn("trend_score", payload["snapshot"]["regime"])
        self.assertIn("chop_score", payload["snapshot"]["regime"])
        self.assertIn("reversal_risk", payload["snapshot"]["regime"])
        self.assertIn("adx_14", payload["snapshot"]["regime"])
        self.assertIn("compression_expansion_state", payload["snapshot"]["regime"])
        self.assertIn("session_cvd", payload["snapshot"]["regime"])

        bars = service.get_bars(metadata["session_id"])
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0]["close"], 19450.0)

        series = service.get_series(
            metadata["session_id"],
            [
                "pressure_index",
                "raw_pressure",
                "pressure_index_weighted",
                "raw_pressure_weighted",
                "regime_state",
                "structure_state",
                "adx_14",
                "session_cvd",
                "compression_score",
                "iv_skew",
            ],
        )
        self.assertEqual(
            sorted(series.keys()),
            [
                "adx_14",
                "compression_score",
                "iv_skew",
                "pressure_index",
                "pressure_index_weighted",
                "raw_pressure",
                "raw_pressure_weighted",
                "regime_state",
                "session_cvd",
                "structure_state",
            ],
        )
        self.assertEqual(len(series["pressure_index"]), 3)
        self.assertEqual(series["raw_pressure"][1]["value"], 17)
        self.assertEqual(series["pressure_index"][1]["value"], 100)
        self.assertEqual(series["raw_pressure_weighted"][1]["value"], 18)
        self.assertEqual(series["pressure_index_weighted"][1]["value"], 100)
        self.assertEqual(len(series["regime_state"]), 3)
        self.assertEqual(len(series["structure_state"]), 3)
        self.assertEqual(len(series["adx_14"]), 3)
        self.assertEqual(len(series["session_cvd"]), 3)

        snapshot_at = service.get_snapshot_at(metadata["session_id"], base_ts + timedelta(seconds=6))
        self.assertIsNotNone(snapshot_at)
        self.assertEqual(snapshot_at["index"], 1)

    def test_create_session_reuses_covering_session(self) -> None:
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
                ),
            ],
        )
        service = OptionPowerReplayService(
            store=store,
            option_root="AUTO",
            expiry_count=2,
            underlying_symbol="MTX",
            snapshot_interval_seconds=5.0,
        )

        full = service.create_session(
            start=base_ts,
            end=base_ts + timedelta(minutes=30),
            set_as_default=True,
        )
        self.assertEqual(store.list_ticks_for_symbols_calls, 1)
        self.assertEqual(store.list_bars_calls, 2)

        subset = service.create_session(
            start=base_ts + timedelta(minutes=5),
            end=base_ts + timedelta(minutes=10),
        )
        self.assertEqual(subset["session_id"], full["session_id"])
        self.assertEqual(store.list_ticks_for_symbols_calls, 1)
        self.assertEqual(store.list_bars_calls, 2)

    def test_get_series_and_bars_support_range_and_interval(self) -> None:
        base_ts = datetime(2026, 4, 16, 9, 0, 0)
        ticks = [
            _tick(
                ts=base_ts,
                symbol="MTX",
                price=19450.0,
                size=1,
                instrument_key="MTX202605",
            ),
            _tick(
                ts=base_ts + timedelta(seconds=5),
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
                ts=base_ts + timedelta(minutes=1, seconds=5),
                symbol="TXX",
                price=121.0,
                size=6,
                instrument_key="TXX20260419400C",
                contract_month="202604",
                strike_price=19400.0,
                call_put="call",
                tick_direction="up",
            ),
        ]
        bars = [
            Bar(
                ts=base_ts + timedelta(minutes=index),
                trading_day=date(2026, 4, 16),
                symbol="MTX",
                contract_month="202605",
                session="day",
                open=19440.0 + index,
                high=19460.0 + index,
                low=19430.0 + index,
                close=19450.0 + index,
                volume=1000.0 + index,
                open_interest=None,
                source="stub_replay",
                instrument_key="MTX202605",
            )
            for index in range(6)
        ]
        store = DummyStore(ticks, bars=bars)
        service = OptionPowerReplayService(
            store=store,
            option_root="AUTO",
            expiry_count=2,
            underlying_symbol="MTX",
            snapshot_interval_seconds=5.0,
        )
        metadata = service.create_session(
            start=base_ts,
            end=base_ts + timedelta(minutes=5),
            set_as_default=True,
        )

        sliced_bars = service.get_bars(
            metadata["session_id"],
            start=base_ts,
            end=base_ts + timedelta(hours=3),
            interval="5m",
        )
        self.assertIsNotNone(sliced_bars)
        self.assertEqual(len(sliced_bars), 2)
        self.assertEqual(sliced_bars[0]["time"], base_ts.isoformat())
        self.assertEqual(sliced_bars[0]["open"], 19440.0)
        self.assertEqual(sliced_bars[0]["close"], 19454.0)
        self.assertEqual(sliced_bars[0]["volume"], 5010.0)

        sliced_series = service.get_series(
            metadata["session_id"],
            ["raw_pressure"],
            start=base_ts,
            end=base_ts + timedelta(minutes=2),
            interval="1m",
        )
        self.assertIsNotNone(sliced_series)
        self.assertEqual(
            [point["time"] for point in sliced_series["raw_pressure"]],
            [
                base_ts.isoformat(),
                (base_ts + timedelta(minutes=1)).isoformat(),
                (base_ts + timedelta(minutes=2)).isoformat(),
            ],
        )

        aggregated_30m_bars = service.get_bars(
            metadata["session_id"],
            start=base_ts,
            end=base_ts + timedelta(minutes=29),
            interval="30m",
        )
        self.assertIsNotNone(aggregated_30m_bars)
        self.assertEqual(len(aggregated_30m_bars), 1)
        self.assertEqual(aggregated_30m_bars[0]["time"], base_ts.isoformat())
        self.assertEqual(aggregated_30m_bars[0]["close"], 19455.0)


if __name__ == "__main__":
    unittest.main()
