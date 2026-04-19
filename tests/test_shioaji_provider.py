import os
import queue
import unittest
from datetime import date, datetime
from unittest.mock import patch

from qt_platform.live.shioaji_provider import (
    ShioajiLiveProvider,
    _available_tx_option_roots,
    _call_put,
    _contract_month,
    _derivative_metadata,
    _extract_tx_option_root,
    _map_tick_direction,
    _nearest_expiry_dates,
    _normalize_root_symbol,
    _root_symbol_for_tick,
    _select_option_contracts_from_roots,
    _select_option_contracts,
)
from qt_platform.domain import CanonicalTick
from qt_platform.settings import ShioajiSettings


class DummyContract:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class DummyEnum:
    def __init__(self, value, name):
        self.value = value
        self.name = name


class DummyQuoteAPI:
    def subscribe(self, contract, quote_type=None, version=None):
        return None

    def unsubscribe(self, contract, quote_type=None, version=None):
        return None


class DummyAPI:
    def __init__(self):
        self.quote = DummyQuoteAPI()
        self.Contracts = DummyContract(Options={})

    def usage(self):
        return DummyContract(
            bytes=0,
            limit_bytes=524_288_000,
            remaining_bytes=524_288_000,
            connections=1,
        )


class DummyShioajiModule:
    class constant:
        class QuoteType:
            Tick = "tick"

        class QuoteVersion:
            v1 = "v1"


class SequencedQueue:
    def __init__(self, events):
        self._events = list(events)

    def get(self, timeout=None):
        if not self._events:
            raise RuntimeError("Queue exhausted during test.")
        event = self._events.pop(0)
        if isinstance(event, BaseException):
            raise event
        return event


class ShioajiProviderHelperTest(unittest.TestCase):
    def test_normalize_root_symbol_extracts_prefix(self) -> None:
        self.assertEqual(_normalize_root_symbol("TXO20250418000C"), "TXO")
        self.assertEqual(_normalize_root_symbol("TX438000D6"), "TX4")
        self.assertEqual(_normalize_root_symbol("TXU17800R6"), "TXU")
        self.assertEqual(_normalize_root_symbol("TXY17800R6"), "TXY")
        self.assertEqual(_normalize_root_symbol("MXFD6"), "MTX")

    def test_extract_tx_option_root_preserves_weekly_and_monthly_roots(self) -> None:
        self.assertEqual(_extract_tx_option_root("TXO17800A6"), "TXO")
        self.assertEqual(_extract_tx_option_root("TX138000D6"), "TX1")
        self.assertEqual(_extract_tx_option_root("TX438000D6"), "TX4")
        self.assertEqual(_extract_tx_option_root("TXU17800R6"), "TXU")
        self.assertEqual(_extract_tx_option_root("TXV17800R6"), "TXV")
        self.assertEqual(_extract_tx_option_root("TXX17800R6"), "TXX")
        self.assertEqual(_extract_tx_option_root("TXY17800R6"), "TXY")
        self.assertEqual(_extract_tx_option_root("TXZ17800R6"), "TXZ")
        self.assertIsNone(_extract_tx_option_root("TXFR1"))

    def test_root_symbol_for_tick_keeps_option_weekly_root(self) -> None:
        contract = DummyContract(code="TX438000D6", symbol="TX4", strike_price=38000.0, option_right="C")
        self.assertEqual(_root_symbol_for_tick("TX438000D6", contract), "TX4")

    def test_root_symbol_for_tick_keeps_friday_weekly_root(self) -> None:
        contract = DummyContract(code="TXU17800R6", symbol="TXU", strike_price=17800.0, option_right="P")
        self.assertEqual(_root_symbol_for_tick("TXU17800R6", contract), "TXU")

    def test_root_symbol_for_tick_keeps_future_root(self) -> None:
        contract = DummyContract(code="TXFR1", symbol="TXFR1")
        self.assertEqual(_root_symbol_for_tick("TXFR1", contract), "TX")

    def test_contract_month_prefers_delivery_fields(self) -> None:
        contract = DummyContract(delivery_month="202504")
        self.assertEqual(_contract_month(contract), "202504")
        contract = DummyContract(delivery_date="202504W2")
        self.assertEqual(_contract_month(contract), "202504W2")

    def test_derivative_metadata_returns_none_for_future_contract(self) -> None:
        contract = DummyContract(code="MXFE6", symbol="MXFE6", strike_price=0.0, option_right="")
        self.assertEqual(_derivative_metadata(contract, "MXFE6"), (None, None))

    def test_derivative_metadata_preserves_option_fields(self) -> None:
        contract = DummyContract(code="TX438000D6", symbol="TX4", strike_price=38000.0, option_right="C")
        self.assertEqual(_derivative_metadata(contract, "TX438000D6"), (38000.0, "call"))

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
        expiries = _nearest_expiry_dates(contracts, expiry_count=2, now=datetime(2026, 4, 16, 10, 0, 0))
        self.assertEqual(expiries, [date(2026, 4, 22), date(2026, 5, 20)])

    def test_nearest_expiry_dates_excludes_today_in_night_session(self) -> None:
        contracts = [
            DummyContract(delivery_date="2026/04/15"),
            DummyContract(delivery_date="2026/04/22"),
            DummyContract(delivery_date="2026/05/20"),
        ]
        expiries = _nearest_expiry_dates(contracts, expiry_count=2, now=datetime(2026, 4, 15, 20, 30, 0))
        self.assertEqual(expiries, [date(2026, 4, 22), date(2026, 5, 20)])

    def test_available_tx_option_roots_filters_tx_family(self) -> None:
        api = DummyContract(Contracts=DummyContract(Options=DummyContract(keys=lambda: ["TXO", "TXX", "TX4", "ABC", "TXFO"])))
        self.assertEqual(_available_tx_option_roots(api), ["TX4", "TXO", "TXX"])

    def test_select_option_contracts_from_roots_uses_one_expiry_per_root(self) -> None:
        api = DummyContract(
            Contracts=DummyContract(
                Options={
                    "TXX": [
                        DummyContract(delivery_date="2026/04/17", strike_price=37100.0, option_right="C", symbol="TXX-C", code="TXXC"),
                        DummyContract(delivery_date="2026/04/17", strike_price=37100.0, option_right="P", symbol="TXX-P", code="TXXP"),
                    ],
                    "TX4": [
                        DummyContract(delivery_date="2026/04/22", strike_price=37200.0, option_right="C", symbol="TX4-C", code="TX4C"),
                        DummyContract(delivery_date="2026/04/22", strike_price=37200.0, option_right="P", symbol="TX4-P", code="TX4P"),
                    ],
                }
            )
        )
        selected = _select_option_contracts_from_roots(
            api=api,
            option_roots=["TXX", "TX4"],
            reference_price=37150.0,
            atm_window=1,
            call_put="both",
        )
        self.assertEqual([contract.symbol for contract in selected], ["TXX-C", "TXX-P", "TX4-C", "TX4-P"])

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

    def test_stream_ticks_keeps_waiting_through_in_session_idle_gap(self) -> None:
        provider = ShioajiLiveProvider(
            settings=ShioajiSettings(usage_check_interval_seconds=9999.0),
            idle_timeout_seconds=0.01,
        )
        provider.connected = True
        provider.api = DummyAPI()
        provider._sj = DummyShioajiModule()
        contract = DummyContract(code="TXFR1")
        tick = CanonicalTick(
            ts=datetime(2026, 4, 15, 21, 1, 0),
            trading_day=date(2026, 4, 15),
            symbol="TX",
            instrument_key="TXFR1",
            contract_month="202604",
            strike_price=None,
            call_put=None,
            session="night",
            price=19500.0,
            size=1.0,
            tick_direction="up",
            source="shioaji_live",
        )
        provider._queue = SequencedQueue([queue.Empty(), tick])

        with patch("qt_platform.live.shioaji_provider.classify_session", return_value="night"):
            ticks = list(provider.stream_ticks_from_contracts([contract], max_events=1))

        self.assertEqual(ticks, [tick])
        self.assertIsNone(provider.stop_reason())

    def test_stream_ticks_stops_after_session_closed_idle_gap(self) -> None:
        provider = ShioajiLiveProvider(
            settings=ShioajiSettings(usage_check_interval_seconds=9999.0),
            idle_timeout_seconds=0.01,
        )
        provider.connected = True
        provider.api = DummyAPI()
        provider._sj = DummyShioajiModule()
        provider._queue = SequencedQueue([queue.Empty()])
        contract = DummyContract(code="TXFR1")

        with patch("qt_platform.live.shioaji_provider.classify_session", return_value="unknown"):
            ticks = list(provider.stream_ticks_from_contracts([contract], max_events=1))

        self.assertEqual(ticks, [])
        self.assertEqual(provider.stop_reason(), "session_closed")


if __name__ == "__main__":
    unittest.main()
