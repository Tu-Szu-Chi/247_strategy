import unittest
from datetime import date, datetime, timedelta

from qt_platform.domain import Bar, CanonicalTick
from qt_platform.option_power.replay import OptionPowerReplayService


class DummyStore:
    def __init__(self, ticks, bars=None):
        self.ticks = ticks
        self.bars = bars or []
        self.list_ticks_for_symbols_calls = 0
        self.list_tick_symbol_stats_calls = 0
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

    def list_tick_symbol_stats(self, symbols, start, end):
        self.list_tick_symbol_stats_calls += 1
        stats = {}
        allowed = set(symbols)
        for tick in self.ticks:
            if tick.symbol not in allowed:
                continue
            if tick.ts < start or tick.ts > end:
                continue
            if tick.strike_price is None or tick.call_put is None:
                continue
            current = stats.get(tick.symbol)
            contract_month = tick.contract_month or "999999"
            if current is None:
                stats[tick.symbol] = {
                    "symbol": tick.symbol,
                    "first_contract_month": contract_month,
                    "tick_count": 1,
                }
                continue
            current["first_contract_month"] = min(current["first_contract_month"], contract_month)
            current["tick_count"] += 1
        return list(stats.values())

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
            end=base_ts + timedelta(seconds=11),
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
        self.assertIn(metadata["compute_status"], {"pending", "running"})
        self.assertEqual(metadata["target_window_bars"], 200)
        self.assertTrue(service.wait_until_ready(metadata["session_id"], timeout=2.0))

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
        self.assertEqual(store.list_tick_symbol_stats_calls, 1)
        self.assertEqual(store.list_ticks_for_symbols_calls, 0)
        self.assertEqual(store.list_bars_calls, 0)

        subset = service.create_session(
            start=base_ts + timedelta(minutes=5),
            end=base_ts + timedelta(minutes=10),
        )
        self.assertEqual(subset["session_id"], full["session_id"])
        self.assertEqual(store.list_tick_symbol_stats_calls, 1)
        self.assertTrue(service.wait_until_ready(full["session_id"], timeout=2.0))
        self.assertEqual(store.list_ticks_for_symbols_calls, 1)

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
        pending_series = service.get_series_payload(
            metadata["session_id"],
            ["raw_pressure"],
            start=base_ts,
            end=base_ts + timedelta(minutes=2),
            interval="1m",
        )
        self.assertIsNotNone(pending_series)
        self.assertIn("partial", pending_series)

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
        self.assertTrue(service.wait_until_ready(metadata["session_id"], timeout=2.0))

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

    def test_get_bars_excludes_unknown_session_boundary_bars_before_aggregation(self) -> None:
        base_ts = datetime(2026, 4, 16, 8, 44, 0)
        bars = [
            Bar(
                ts=base_ts,
                trading_day=date(2026, 4, 16),
                symbol="MTX",
                contract_month="202605",
                session="unknown",
                open=19400.0,
                high=19401.0,
                low=19400.0,
                close=19401.0,
                volume=10.0,
                open_interest=None,
                source="stub_replay",
                instrument_key="MTX202605",
            ),
            *[
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
                for index in range(1, 6)
            ],
        ]
        store = DummyStore([], bars=bars)
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

        one_minute_bars = service.get_bars(
            metadata["session_id"],
            start=base_ts,
            end=base_ts + timedelta(minutes=5),
            interval="1m",
        )
        self.assertIsNotNone(one_minute_bars)
        self.assertEqual(one_minute_bars[0]["time"], "2026-04-16T08:45:00")

        five_minute_bars = service.get_bars(
            metadata["session_id"],
            start=base_ts,
            end=base_ts + timedelta(minutes=5),
            interval="5m",
        )
        self.assertIsNotNone(five_minute_bars)
        self.assertEqual(five_minute_bars[0]["time"], "2026-04-16T08:45:00")

    def test_get_bars_aggregates_full_buckets_for_overlapping_windows(self) -> None:
        base_ts = datetime(2026, 4, 16, 9, 15, 0)
        bars = [
            Bar(
                ts=base_ts + timedelta(minutes=index),
                trading_day=date(2026, 4, 16),
                symbol="MTX",
                contract_month="202605",
                session="day",
                open=100.0 + index,
                high=101.0 + index,
                low=99.0 + index,
                close=100.5 + index,
                volume=10.0 + index,
                open_interest=None,
                source="stub_replay",
                instrument_key="MTX202605",
            )
            for index in range(10)
        ]
        store = DummyStore([], bars=bars)
        service = OptionPowerReplayService(
            store=store,
            option_root="AUTO",
            expiry_count=2,
            underlying_symbol="MTX",
            snapshot_interval_seconds=5.0,
        )
        metadata = service.create_session(
            start=base_ts,
            end=base_ts + timedelta(minutes=9),
            set_as_default=True,
        )

        aligned = service.get_bars(
            metadata["session_id"],
            start=base_ts + timedelta(minutes=5),
            end=base_ts + timedelta(minutes=9),
            interval="5m",
        )
        partial_overlap = service.get_bars(
            metadata["session_id"],
            start=base_ts + timedelta(minutes=7),
            end=base_ts + timedelta(minutes=9),
            interval="5m",
        )

        self.assertIsNotNone(aligned)
        self.assertIsNotNone(partial_overlap)
        self.assertEqual(aligned, partial_overlap)
        self.assertEqual(aligned[0]["time"], "2026-04-16T09:20:00")
        self.assertEqual(aligned[0]["open"], 105.0)
        self.assertEqual(aligned[0]["close"], 109.5)
        self.assertEqual(aligned[0]["volume"], 85.0)

    def test_get_bundle_by_bars_uses_existing_bars_across_calendar_gaps(self) -> None:
        friday = datetime(2026, 4, 17, 13, 44, 0)
        monday = datetime(2026, 4, 20, 8, 45, 0)
        bars = [
            Bar(
                ts=friday,
                trading_day=date(2026, 4, 17),
                symbol="MTX",
                contract_month="202605",
                session="day",
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                volume=10.0,
                open_interest=None,
                source="stub_replay",
                instrument_key="MTX202605",
            ),
            Bar(
                ts=monday,
                trading_day=date(2026, 4, 20),
                symbol="MTX",
                contract_month="202605",
                session="day",
                open=110.0,
                high=111.0,
                low=109.0,
                close=110.5,
                volume=20.0,
                open_interest=None,
                source="stub_replay",
                instrument_key="MTX202605",
            ),
        ]
        store = DummyStore([], bars=bars)
        service = OptionPowerReplayService(
            store=store,
            option_root="AUTO",
            expiry_count=2,
            underlying_symbol="MTX",
            snapshot_interval_seconds=5.0,
        )
        metadata = service.create_session(
            start=friday,
            end=monday,
            set_as_default=True,
        )

        payload = service.get_bundle_by_bars(
            metadata["session_id"],
            ["raw_pressure"],
            anchor=friday,
            direction="next",
            bar_count=1,
            interval="1m",
        )

        self.assertIsNotNone(payload)
        self.assertEqual(payload["bars"][0]["time"], "2026-04-20T08:45:00")
        self.assertEqual(payload["coverage"]["bar_count"], 1)
        self.assertEqual(payload["coverage"]["first_bar_time"], "2026-04-20T08:45:00")

    def test_get_bundle_by_bars_finds_previous_bars_outside_current_session(self) -> None:
        friday = datetime(2026, 4, 17, 13, 44, 0)
        monday = datetime(2026, 4, 20, 8, 45, 0)
        bars = [
            Bar(
                ts=friday,
                trading_day=date(2026, 4, 17),
                symbol="MTX",
                contract_month="202605",
                session="day",
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                volume=10.0,
                open_interest=None,
                source="stub_replay",
                instrument_key="MTX202605",
            ),
            Bar(
                ts=monday,
                trading_day=date(2026, 4, 20),
                symbol="MTX",
                contract_month="202605",
                session="day",
                open=110.0,
                high=111.0,
                low=109.0,
                close=110.5,
                volume=20.0,
                open_interest=None,
                source="stub_replay",
                instrument_key="MTX202605",
            ),
        ]
        store = DummyStore([], bars=bars)
        service = OptionPowerReplayService(
            store=store,
            option_root="AUTO",
            expiry_count=2,
            underlying_symbol="MTX",
            snapshot_interval_seconds=5.0,
        )
        metadata = service.create_session(
            start=monday,
            end=monday,
            set_as_default=True,
        )

        payload = service.get_bundle_by_bars(
            metadata["session_id"],
            ["raw_pressure"],
            anchor=monday,
            direction="prev",
            bar_count=1,
            interval="1m",
        )

        self.assertIsNotNone(payload)
        self.assertEqual(payload["bars"][0]["time"], "2026-04-17T13:44:00")
        self.assertEqual(payload["session"]["session_id"], metadata["session_id"])
        self.assertTrue(payload["partial"])
        self.assertEqual(payload["series"], {"raw_pressure": []})


if __name__ == "__main__":
    unittest.main()
