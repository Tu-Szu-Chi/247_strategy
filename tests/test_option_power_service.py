import unittest
from datetime import date, datetime
from unittest.mock import patch

from qt_platform.domain import CanonicalTick
from qt_platform.option_power.service import OPTION_ROOT_RETRY_SECONDS, OptionPowerRuntimeService


class DummyProvider:
    def __init__(self) -> None:
        self.connected = False
        self.closed = False

    def connect(self) -> None:
        self.connected = True

    def close(self) -> None:
        self.closed = True
        self.connected = False

    def resolve_option_universe(self, **kwargs):
        raise ValueError("No option contracts found for roots '[]'.")

    def option_root_diagnostics(self, now=None) -> dict:
        return {
            "available_roots": [],
            "roots": [],
        }


class DummyStore:
    def append_ticks(self, ticks):
        return 0

    def upsert_bars(self, timeframe, bars):
        return 0

    def upsert_minute_force_features(self, features):
        return 0

    def create_live_run(self, metadata) -> None:
        return None


class StreamingProvider(DummyProvider):
    def __init__(self, ticks, contracts, underlying_contract) -> None:
        super().__init__()
        self._ticks = ticks
        self._contracts = {}
        self._resolved_contract = underlying_contract
        self._option_contracts = contracts

    def resolve_option_universe(self, **kwargs):
        return ["TX4"], self._option_contracts, 20000.0

    def _resolve_contract(self, symbol):
        return self._resolved_contract

    def stream_ticks_from_contracts(self, contracts, max_events=None):
        for tick in self._ticks:
            yield tick

    def stop_reason(self):
        return "completed"


class OptionPowerRuntimeServiceTest(unittest.TestCase):
    def test_run_cycle_waits_for_option_roots_instead_of_crashing(self) -> None:
        logs = []
        provider = DummyProvider()
        service = OptionPowerRuntimeService(
            provider=provider,
            store=DummyStore(),
            option_root="AUTO",
            expiry_count=2,
            atm_window=20,
            underlying_future_symbol="MXFR1",
            call_put="both",
            session_scope="day_and_night",
            batch_size=500,
            snapshot_interval_seconds=5.0,
            log_callback=logs.append,
        )
        service.run_id = "test-run"

        with patch("qt_platform.option_power.service.time.sleep") as sleep_mock:
            service._run_cycle()

        self.assertEqual(service.status, "waiting_for_option_roots")
        self.assertEqual(service.warning, "No option contracts found for roots '[]'.")
        self.assertTrue(provider.closed)
        self.assertEqual(sleep_mock.call_args[0][0], OPTION_ROOT_RETRY_SECONDS)
        self.assertEqual(logs[0]["status"], "connected")
        self.assertEqual(logs[1]["status"], "waiting_for_option_roots")
        self.assertEqual(logs[1]["available_option_roots"], [])

    def test_run_cycle_treats_underlying_tick_by_instrument_key(self) -> None:
        option_contract = type(
            "OptionContract",
            (),
            {
                "code": "TX420260420000C",
                "symbol": "TX4C",
                "delivery_date": "2026/04/22",
                "strike_price": 20000.0,
                "option_right": "call",
            },
        )()
        underlying_contract = type(
            "UnderlyingContract",
            (),
            {
                "code": "MXF202604",
                "target_code": "MXFR1",
            },
        )()
        ticks = [
            CanonicalTick(
                ts=datetime(2026, 4, 20, 9, 0, 1),
                trading_day=date(2026, 4, 20),
                symbol="MTX",
                instrument_key="MXF202604",
                contract_month="202604",
                strike_price=None,
                call_put=None,
                session="day",
                price=20001.0,
                size=1.0,
                tick_direction="up",
                source="shioaji_live",
            )
        ]
        service = OptionPowerRuntimeService(
            provider=StreamingProvider(ticks, [option_contract], underlying_contract),
            store=DummyStore(),
            option_root="AUTO",
            expiry_count=2,
            atm_window=20,
            underlying_future_symbol="MXFR1",
            call_put="both",
            session_scope="day_and_night",
            batch_size=500,
            snapshot_interval_seconds=5.0,
            log_callback=lambda payload: None,
        )
        service.run_id = "test-run"

        service._run_cycle()

        bars = service.live_bars()
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0]["close"], 20001.0)


if __name__ == "__main__":
    unittest.main()
