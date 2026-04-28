import unittest
from datetime import datetime

from qt_platform.option_iv import black76_price, build_iv_surface, implied_volatility
from qt_platform.option_power.domain import OptionContractSnapshot, OptionExpirySnapshot


class OptionIvTest(unittest.TestCase):
    def test_implied_volatility_round_trips_black76_price(self) -> None:
        price = black76_price(
            forward=20000.0,
            strike=20200.0,
            time_to_expiry_years=5 / 252,
            volatility=0.28,
            call_put="call",
        )

        iv = implied_volatility(
            option_price=price,
            forward=20000.0,
            strike=20200.0,
            time_to_expiry_years=5 / 252,
            call_put="call",
        )

        self.assertIsNotNone(iv)
        self.assertAlmostEqual(iv or 0, 0.28, places=5)

    def test_surface_keeps_otm_call_and_put_and_computes_skew(self) -> None:
        generated_at = datetime(2026, 4, 21, 13, 30, 0)
        time_to_expiry_years = 1 / 252
        call_price = black76_price(
            forward=100.0,
            strike=101.0,
            time_to_expiry_years=time_to_expiry_years,
            volatility=0.25,
            call_put="call",
        )
        put_price = black76_price(
            forward=100.0,
            strike=99.0,
            time_to_expiry_years=time_to_expiry_years,
            volatility=0.20,
            call_put="put",
        )
        itm_call_price = black76_price(
            forward=100.0,
            strike=99.0,
            time_to_expiry_years=time_to_expiry_years,
            volatility=0.30,
            call_put="call",
        )
        expiry = OptionExpirySnapshot(
            contract_month="20260422",
            label="2026-04-22",
            contracts=[
                _contract("C101", strike=101.0, call_put="call", last_price=call_price),
                _contract("P99", strike=99.0, call_put="put", last_price=put_price),
                _contract("C99", strike=99.0, call_put="call", last_price=itm_call_price),
            ],
        )

        surface = build_iv_surface(
            generated_at=generated_at,
            underlying_reference_price=100.0,
            underlying_reference_source="test",
            expiries=[expiry],
        )

        self.assertIsNotNone(surface)
        self.assertEqual(len(surface.expiries), 1)
        self.assertEqual([point.instrument_key for point in surface.expiries[0].points], ["P99", "C101"])
        self.assertAlmostEqual(surface.expiries[0].put_wing_iv or 0, 0.20, places=5)
        self.assertAlmostEqual(surface.expiries[0].call_wing_iv or 0, 0.25, places=5)
        self.assertAlmostEqual(surface.expiries[0].skew or 0, 0.05, places=5)
        self.assertAlmostEqual(surface.skew or 0, 0.05, places=5)
        self.assertAlmostEqual(surface.skew_intensity or 0, 0.05, places=5)


def _contract(
    instrument_key: str,
    *,
    strike: float,
    call_put: str,
    last_price: float,
    last_tick_ts: str = "2026-04-21T13:29:30",
) -> OptionContractSnapshot:
    return OptionContractSnapshot(
        instrument_key=instrument_key,
        symbol="TXO",
        contract_month="20260422",
        strike_price=strike,
        call_put=call_put,
        last_price=last_price,
        cumulative_buy_volume=0.0,
        cumulative_sell_volume=0.0,
        cumulative_power=0.0,
        rolling_1m_buy_volume=0.0,
        rolling_1m_sell_volume=0.0,
        power_1m_delta=0.0,
        unknown_volume=0.0,
        last_tick_ts=last_tick_ts,
    )


if __name__ == "__main__":
    unittest.main()
