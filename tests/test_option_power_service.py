import unittest
from unittest.mock import patch

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
            underlying_future_symbol="TXFR1",
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


if __name__ == "__main__":
    unittest.main()
