import unittest
from datetime import date, datetime, timedelta

from qt_platform.domain import CanonicalTick
from qt_platform.option_iv import black76_price
from qt_platform.option_power import OptionPowerAggregator


def _tick(
    *,
    ts: datetime,
    session: str,
    direction: str | None,
    size: float,
    instrument_key: str = "TXO202504W218000C",
    contract_month: str = "202504W2",
    strike_price: float = 18000.0,
    call_put: str = "call",
    price: float = 12.0,
) -> CanonicalTick:
    return CanonicalTick(
        ts=ts,
        trading_day=date(2025, 4, 11),
        symbol="TXO",
        instrument_key=instrument_key,
        contract_month=contract_month,
        strike_price=strike_price,
        call_put=call_put,
        session=session,
        price=price,
        size=size,
        tick_direction=direction,
        source="stub_live",
    )


class OptionPowerAggregatorTest(unittest.TestCase):
    def test_snapshot_tracks_cumulative_and_rolling_power(self) -> None:
        aggregator = OptionPowerAggregator(option_root="TXO")
        base_ts = datetime(2025, 4, 11, 9, 0, 0)
        aggregator.ingest_tick(_tick(ts=base_ts, session="day", direction="up", size=10))
        aggregator.ingest_tick(_tick(ts=base_ts + timedelta(seconds=10), session="day", direction="down", size=3))
        aggregator.ingest_tick(_tick(ts=base_ts + timedelta(seconds=20), session="day", direction=None, size=2))

        snapshot = aggregator.snapshot(
            generated_at=base_ts + timedelta(seconds=30),
            run_id="run-1",
            underlying_reference_price=18000.0,
            underlying_reference_source="twii",
            status="running",
        )

        self.assertEqual(snapshot.session, "day")
        self.assertEqual(snapshot.underlying_reference_source, "twii")
        self.assertEqual(snapshot.contract_count, 1)
        contract = snapshot.expiries[0].contracts[0]
        self.assertEqual(contract.cumulative_buy_volume, 10)
        self.assertEqual(contract.cumulative_sell_volume, 3)
        self.assertEqual(contract.cumulative_power, 7)
        self.assertEqual(contract.rolling_1m_buy_volume, 10)
        self.assertEqual(contract.rolling_1m_sell_volume, 3)
        self.assertEqual(contract.power_1m_delta, 7)
        self.assertEqual(contract.unknown_volume, 2)
        self.assertEqual(snapshot.raw_pressure, 7)
        self.assertEqual(snapshot.pressure_index, 54)
        self.assertEqual(snapshot.raw_pressure_weighted, 7)
        self.assertEqual(snapshot.pressure_index_weighted, 50)

    def test_snapshot_evicts_old_rolling_events(self) -> None:
        aggregator = OptionPowerAggregator(option_root="TXO")
        base_ts = datetime(2025, 4, 11, 9, 0, 0)
        aggregator.ingest_tick(_tick(ts=base_ts, session="day", direction="up", size=10))
        aggregator.ingest_tick(_tick(ts=base_ts + timedelta(seconds=70), session="day", direction="down", size=4))

        snapshot = aggregator.snapshot(
            generated_at=base_ts + timedelta(seconds=70),
            run_id="run-1",
            underlying_reference_price=None,
            underlying_reference_source=None,
            status="running",
        )

        contract = snapshot.expiries[0].contracts[0]
        self.assertEqual(contract.cumulative_power, 6)
        self.assertEqual(contract.rolling_1m_buy_volume, 0)
        self.assertEqual(contract.rolling_1m_sell_volume, 4)
        self.assertEqual(contract.power_1m_delta, -4)

    def test_session_change_resets_cumulative_state(self) -> None:
        aggregator = OptionPowerAggregator(option_root="TXO")
        base_ts = datetime(2025, 4, 11, 13, 44, 50)
        aggregator.ingest_tick(_tick(ts=base_ts, session="day", direction="up", size=10))
        aggregator.ingest_tick(_tick(ts=base_ts + timedelta(minutes=80), session="night", direction="down", size=4))

        snapshot = aggregator.snapshot(
            generated_at=base_ts + timedelta(minutes=80),
            run_id="run-1",
            underlying_reference_price=None,
            underlying_reference_source=None,
            status="running",
        )

        self.assertEqual(snapshot.session, "night")
        contract = snapshot.expiries[0].contracts[0]
        self.assertEqual(contract.cumulative_buy_volume, 0)
        self.assertEqual(contract.cumulative_sell_volume, 4)
        self.assertEqual(contract.cumulative_power, -4)

    def test_snapshot_formats_expiry_labels_for_weekly_and_monthly_contracts(self) -> None:
        aggregator = OptionPowerAggregator(option_root="TXO")
        base_ts = datetime(2025, 4, 11, 9, 0, 0)
        aggregator.ingest_tick(
            _tick(
                ts=base_ts,
                session="day",
                direction="up",
                size=10,
                instrument_key="TXO202504W218000C",
                contract_month="202504W2",
            )
        )
        aggregator.ingest_tick(
            _tick(
                ts=base_ts + timedelta(seconds=1),
                session="day",
                direction="up",
                size=5,
                instrument_key="TXO20250518000C",
                contract_month="202505",
            )
        )

        snapshot = aggregator.snapshot(
            generated_at=base_ts + timedelta(seconds=5),
            run_id="run-1",
            underlying_reference_price=None,
            underlying_reference_source=None,
            status="running",
        )

        self.assertEqual([expiry.contract_month for expiry in snapshot.expiries], ["202504W2", "202505"])
        self.assertEqual([expiry.label for expiry in snapshot.expiries], ["2025-04 W2", "2025-05"])

    def test_snapshot_formats_expiry_labels_for_exact_delivery_date(self) -> None:
        aggregator = OptionPowerAggregator(option_root="TXY")
        base_ts = datetime(2025, 4, 11, 9, 0, 0)
        aggregator.ingest_tick(
            _tick(
                ts=base_ts,
                session="day",
                direction="up",
                size=5,
                instrument_key="TXY2026042438200C",
                contract_month="20260424",
                strike_price=38200.0,
                call_put="call",
            )
        )

        snapshot = aggregator.snapshot(
            generated_at=base_ts + timedelta(seconds=5),
            run_id="run-1",
            underlying_reference_price=None,
            underlying_reference_source=None,
            status="running",
        )

        self.assertEqual(snapshot.expiries[0].contract_month, "20260424")
        self.assertEqual(snapshot.expiries[0].label, "2026-04-24")

    def test_snapshot_uses_updated_option_roots_metadata(self) -> None:
        aggregator = OptionPowerAggregator(option_root="AUTO")
        aggregator.set_option_root("TXX,TX4")

        snapshot = aggregator.snapshot(
            generated_at=datetime(2025, 4, 11, 9, 0, 0),
            run_id="run-1",
            underlying_reference_price=None,
            underlying_reference_source=None,
            status="running",
        )

        self.assertEqual(snapshot.option_root, "TXX,TX4")

    def test_snapshot_computes_weighted_pressure_across_calls_and_puts(self) -> None:
        aggregator = OptionPowerAggregator(option_root="TXO")
        base_ts = datetime(2025, 4, 11, 9, 0, 0)
        aggregator.ingest_tick(
            _tick(
                ts=base_ts,
                session="day",
                direction="up",
                size=10,
                instrument_key="TXO202504W218000C",
                contract_month="202504W2",
                strike_price=18000.0,
                call_put="call",
            )
        )
        aggregator.ingest_tick(
            _tick(
                ts=base_ts + timedelta(seconds=1),
                session="day",
                direction="down",
                size=10,
                instrument_key="TXO202504W218100P",
                contract_month="202504W2",
                strike_price=18100.0,
                call_put="put",
            )
        )
        aggregator.ingest_tick(
            _tick(
                ts=base_ts + timedelta(seconds=2),
                session="day",
                direction="down",
                size=10,
                instrument_key="TXO20250518200C",
                contract_month="202505",
                strike_price=18200.0,
                call_put="call",
            )
        )

        snapshot = aggregator.snapshot(
            generated_at=base_ts + timedelta(seconds=30),
            run_id="run-1",
            underlying_reference_price=18000.0,
            underlying_reference_source="twii",
            status="running",
        )

        self.assertEqual(snapshot.raw_pressure, 14)
        self.assertEqual(snapshot.pressure_index, 61)
        self.assertEqual(snapshot.raw_pressure_weighted, 15)
        self.assertEqual(snapshot.pressure_index_weighted, 60)

    def test_snapshot_includes_iv_surface_for_fresh_otm_options(self) -> None:
        aggregator = OptionPowerAggregator(option_root="TXO")
        base_ts = datetime(2026, 4, 21, 13, 29, 30)
        time_to_expiry_years = 1 / 252
        aggregator.ingest_tick(
            _tick(
                ts=base_ts,
                session="day",
                direction="up",
                size=1,
                instrument_key="TXO2026042210100C",
                contract_month="20260422",
                strike_price=10100.0,
                call_put="call",
                price=black76_price(
                    forward=10000.0,
                    strike=10100.0,
                    time_to_expiry_years=time_to_expiry_years,
                    volatility=0.25,
                    call_put="call",
                ),
            )
        )
        aggregator.ingest_tick(
            _tick(
                ts=base_ts,
                session="day",
                direction="up",
                size=1,
                instrument_key="TXO202604229900P",
                contract_month="20260422",
                strike_price=9900.0,
                call_put="put",
                price=black76_price(
                    forward=10000.0,
                    strike=9900.0,
                    time_to_expiry_years=time_to_expiry_years,
                    volatility=0.20,
                    call_put="put",
                ),
            )
        )

        snapshot = aggregator.snapshot(
            generated_at=datetime(2026, 4, 21, 13, 30, 0),
            run_id="run-1",
            underlying_reference_price=10000.0,
            underlying_reference_source="twii",
            status="running",
        )

        self.assertIsNotNone(snapshot.iv_surface)
        self.assertEqual(len(snapshot.iv_surface.expiries), 1)
        self.assertAlmostEqual(snapshot.iv_surface.skew or 0, 0.05, places=5)
        self.assertAlmostEqual(snapshot.iv_surface.expiries[0].skew or 0, 0.05, places=5)


if __name__ == "__main__":
    unittest.main()
