import os
import unittest
from datetime import date

from qt_platform.live.shioaji_provider import (
    _call_put,
    _contract_month,
    _map_tick_direction,
    _nearest_expiry_dates,
    _normalize_root_symbol,
    _select_option_contracts,
)
from qt_platform.settings import ShioajiSettings


class DummyContract:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class DummyEnum:
    def __init__(self, value, name):
        self.value = value
        self.name = name


class ShioajiProviderHelperTest(unittest.TestCase):
    def test_normalize_root_symbol_extracts_prefix(self) -> None:
        self.assertEqual(_normalize_root_symbol("TXO20250418000C"), "TXO")

    def test_contract_month_prefers_delivery_fields(self) -> None:
        contract = DummyContract(delivery_month="202504")
        self.assertEqual(_contract_month(contract), "202504")
        contract = DummyContract(delivery_date="202504W2")
        self.assertEqual(_contract_month(contract), "202504W2")

    def test_call_put_normalization(self) -> None:
        self.assertEqual(_call_put(DummyContract(option_right="C")), "call")
        self.assertEqual(_call_put(DummyContract(option_right="Put")), "put")
        self.assertIsNone(_call_put(DummyContract()))

    def test_tick_direction_mapping(self) -> None:
        self.assertEqual(_map_tick_direction(DummyEnum(1, "Buy")), "up")
        self.assertEqual(_map_tick_direction(DummyEnum(2, "Sell")), "down")
        self.assertIsNone(_map_tick_direction(DummyEnum(0, "None")))

    def test_settings_accept_secret_typo_fallback(self) -> None:
        original = os.environ.get("SH_SECRET_KEY")
        os.environ["SH_SECRET_KEY"] = "fallback-secret"
        try:
            settings = ShioajiSettings()
            self.assertEqual(settings.secret_key, "fallback-secret")
        finally:
            if original is None:
                os.environ.pop("SH_SECRET_KEY", None)
            else:
                os.environ["SH_SECRET_KEY"] = original

    def test_nearest_expiry_dates_prefers_future_dates(self) -> None:
        contracts = [
            DummyContract(delivery_date="2026/04/15"),
            DummyContract(delivery_date="2026/04/22"),
            DummyContract(delivery_date="2026/05/20"),
        ]
        expiries = _nearest_expiry_dates(contracts, expiry_count=2, today=date(2026, 4, 16))
        self.assertEqual(expiries, [date(2026, 4, 22), date(2026, 5, 20)])

    def test_select_option_contracts_picks_nearest_two_expiries_and_atm_window(self) -> None:
        contracts = []
        for delivery in ("2026/04/15", "2026/04/22", "2026/05/20"):
            for strike in (17000.0, 17100.0, 17200.0):
                contracts.append(
                    DummyContract(
                        delivery_date=delivery,
                        strike_price=strike,
                        option_right="C",
                        symbol=f"TXO{delivery}-{strike}-C",
                    )
                )
                contracts.append(
                    DummyContract(
                        delivery_date=delivery,
                        strike_price=strike,
                        option_right="P",
                        symbol=f"TXO{delivery}-{strike}-P",
                    )
                )
        selected = _select_option_contracts(
            contracts=contracts,
            expiry_dates=[date(2026, 4, 15), date(2026, 4, 22)],
            reference_price=17120.0,
            atm_window=1,
            call_put="both",
        )
        self.assertEqual(len(selected), 12)
        self.assertTrue(all("2026/05/20" not in contract.symbol for contract in selected))
        self.assertTrue(all(any(strike in contract.symbol for strike in ("17000.0", "17100.0", "17200.0")) for contract in selected))


if __name__ == "__main__":
    unittest.main()
