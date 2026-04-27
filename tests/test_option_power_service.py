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
    def __init__(self) -> None:
        self.upserted_bars = []

    def append_ticks(self, ticks):
        return 0

    def upsert_bars(self, timeframe, bars):
        self.upserted_bars.extend(list(bars))
        return 0

    def upsert_minute_force_features(self, features):
        return 0

    def create_live_run(self, metadata) -> None:
        return None


class StreamingProvider(DummyProvider):
    def __init__(self, ticks, contracts, underlying_contract, indicator_contract=None, indicator_price=19555.0) -> None:
        super().__init__()
        self._ticks = ticks
        self._contracts = {}
        self._resolved_contract = underlying_contract
        self._indicator_contract = indicator_contract or type(
            "IndicatorContract",
            (),
            {
                "code": "001",
                "symbol": "TSE001",
            },
        )()
        self._indicator_price = indicator_price
        self._option_contracts = contracts

    def resolve_option_universe(self, **kwargs):
        return ["TX4"], self._option_contracts, 20000.0

    def _resolve_contract(self, symbol):
        return self._resolved_contract

    def resolve_taiex_contract(self):
        return self._indicator_contract

    def snapshot_price(self, contract, timeout=5000):
        return self._indicator_price

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

    def test_run_cycle_uses_day_index_for_indicator_reference(self) -> None:
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
        indicator_contract = type(
            "IndicatorContract",
            (),
            {
                "code": "001",
                "target_code": "",
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
            provider=StreamingProvider(ticks, [option_contract], underlying_contract, indicator_contract, indicator_price=19555.0),
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
        service._refresh_day_indicator_snapshot(datetime(2026, 4, 20, 9, 0, 2))
        service._refresh_indicator_reference(datetime(2026, 4, 20, 9, 0, 2))

        snapshot = service.current_snapshot()
        self.assertEqual(snapshot["underlying_reference_price"], 19555.0)
        self.assertEqual(snapshot["underlying_reference_source"], "twii")

    def test_run_cycle_keeps_future_reference_during_night_session(self) -> None:
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
                ts=datetime(2026, 4, 20, 21, 0, 1),
                trading_day=date(2026, 4, 20),
                symbol="MTX",
                instrument_key="MXF202604",
                contract_month="202604",
                strike_price=None,
                call_put=None,
                session="night",
                price=20088.0,
                size=1.0,
                tick_direction="up",
                source="shioaji_live",
            )
        ]
        service = OptionPowerRuntimeService(
            provider=StreamingProvider(ticks, [option_contract], underlying_contract, indicator_price=19555.0),
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

        snapshot = service.current_snapshot()
        self.assertEqual(snapshot["underlying_reference_price"], 20088.0)
        self.assertEqual(snapshot["underlying_reference_source"], "mxfr1")

    def test_refresh_day_indicator_snapshot_persists_bar_to_store(self) -> None:
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
        store = DummyStore()
        provider = StreamingProvider([], [option_contract], underlying_contract, indicator_price=19555.0)
        service = OptionPowerRuntimeService(
            provider=provider,
            store=store,
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
        service.provider.connect()
        service._day_indicator_contract = service.provider.resolve_taiex_contract()
        service._refresh_day_indicator_snapshot(datetime(2026, 4, 20, 9, 0, 1))
        service.provider.close()

        twii_bars = [bar for bar in store.upserted_bars if bar.symbol == "TWII"]
        self.assertTrue(twii_bars)
        self.assertEqual(twii_bars[-1].instrument_key, "index:TWII")
        self.assertEqual(twii_bars[-1].build_source, "live_snapshot_agg")

    def test_live_series_exposes_base_and_weighted_series(self) -> None:
        service = OptionPowerRuntimeService(
            provider=DummyProvider(),
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
        service._snapshot_history.extend(
            [
                {
                    "session_id": "test-run",
                    "index": 0,
                    "simulated_at": "2026-04-20T09:00:00",
                    "snapshot": {
                        "pressure_index": 5,
                        "raw_pressure": 12,
                        "pressure_index_weighted": 4,
                        "raw_pressure_weighted": 11,
                        "regime": {
                            "generated_at": "2026-04-20T09:00:00",
                            "session": "day",
                            "close": 20000.0,
                            "session_vwap": 19998.0,
                            "vwap_distance_bps": 1.0,
                            "directional_efficiency_15m": 0.4,
                            "vwap_cross_count_15m": 1,
                            "tick_imbalance_5m": 0.2,
                            "trade_intensity_5m": 3,
                            "trade_intensity_ratio_30m": 1.0,
                            "range_ratio_5m_30m": 0.2,
                            "adx_14": 20.0,
                            "plus_di_14": 22.0,
                            "minus_di_14": 10.0,
                            "di_bias_14": 12.0,
                            "choppiness_14": 45.0,
                            "compression_score": 10,
                            "expansion_score": 65,
                            "compression_expansion_state": "expanding",
                            "session_cvd": 15.0,
                            "cvd_5m_delta": 7.0,
                            "cvd_15m_delta": 10.0,
                            "cvd_5m_slope": 2.0,
                            "price_cvd_divergence_15m": "none",
                            "cvd_price_alignment": "aligned_up",
                            "trend_score": 55,
                            "chop_score": 25,
                            "reversal_risk": 10,
                            "regime_label": "trend_up",
                        },
                    },
                },
                {
                    "session_id": "test-run",
                    "index": 1,
                    "simulated_at": "2026-04-20T09:00:05",
                    "snapshot": {
                        "pressure_index": 17,
                        "raw_pressure": 18,
                        "pressure_index_weighted": 14,
                        "raw_pressure_weighted": 16,
                        "regime": {
                            "generated_at": "2026-04-20T09:00:05",
                            "session": "day",
                            "close": 20005.0,
                            "session_vwap": 20000.0,
                            "vwap_distance_bps": 2.5,
                            "directional_efficiency_15m": 0.6,
                            "vwap_cross_count_15m": 0,
                            "tick_imbalance_5m": 0.4,
                            "trade_intensity_5m": 5,
                            "trade_intensity_ratio_30m": 1.2,
                            "range_ratio_5m_30m": 0.3,
                            "adx_14": 24.0,
                            "plus_di_14": 25.0,
                            "minus_di_14": 9.0,
                            "di_bias_14": 16.0,
                            "choppiness_14": 38.0,
                            "compression_score": 5,
                            "expansion_score": 72,
                            "compression_expansion_state": "expanding",
                            "session_cvd": 28.0,
                            "cvd_5m_delta": 12.0,
                            "cvd_15m_delta": 18.0,
                            "cvd_5m_slope": 2.4,
                            "price_cvd_divergence_15m": "none",
                            "cvd_price_alignment": "aligned_up",
                            "trend_score": 68,
                            "chop_score": 18,
                            "reversal_risk": 8,
                            "regime_label": "trend_up",
                        },
                    },
                },
            ]
        )

        series = service.live_series(
            [
                "pressure_index",
                "raw_pressure",
                "pressure_index_weighted",
                "raw_pressure_weighted",
                "regime_state",
                "structure_state",
                "adx_14",
                "session_cvd",
            ]
        )

        self.assertEqual(series["pressure_index"][1]["value"], 17)
        self.assertEqual(series["raw_pressure"][1]["value"], 18)
        self.assertEqual(series["pressure_index_weighted"][1]["value"], 14)
        self.assertEqual(series["raw_pressure_weighted"][1]["value"], 16)
        self.assertEqual(series["regime_state"][1]["value"], 1)
        self.assertEqual(series["adx_14"][1]["value"], 24.0)
        self.assertEqual(series["session_cvd"][1]["value"], 28.0)
        self.assertEqual(len(series["structure_state"]), 2)

        metadata = service.live_metadata()
        self.assertIn("regime_state", metadata["available_series"])
        self.assertIn("adx_14", metadata["available_series"])
        self.assertIn("regime_schema", metadata)


if __name__ == "__main__":
    unittest.main()
