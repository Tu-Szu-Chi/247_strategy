import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from qt_platform.domain import Bar, CanonicalTick
from qt_platform.kronos.probability import ProbabilityTarget
from qt_platform.monitor.service import (
    OPTION_ROOT_RETRY_SECONDS,
    KronosLiveSettings,
    RealtimeMonitorService,
)


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
        self.live_runs = []

    def append_ticks(self, ticks):
        return 0

    def upsert_bars(self, timeframe, bars):
        self.upserted_bars.extend(list(bars))
        return 0

    def upsert_minute_force_features(self, features):
        return 0

    def create_live_run(self, metadata) -> None:
        self.live_runs.append(metadata)
        return None


class StreamingProvider(DummyProvider):
    def __init__(
        self,
        ticks,
        contracts,
        underlying_contract,
        indicator_contract=None,
        indicator_price=19555.0,
        symbol_contracts=None,
    ) -> None:
        super().__init__()
        self._ticks = ticks
        self._contracts = {}
        self._resolved_contract = underlying_contract
        self._symbol_contracts = symbol_contracts or {}
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
        if symbol in self._symbol_contracts:
            return self._symbol_contracts[symbol]
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


class RealtimeMonitorServiceTest(unittest.TestCase):
    def test_run_cycle_waits_for_option_roots_instead_of_crashing(self) -> None:
        logs = []
        provider = DummyProvider()
        service = RealtimeMonitorService(
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

        with patch("qt_platform.monitor.service.time.sleep") as sleep_mock:
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
        service = RealtimeMonitorService(
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
        service = RealtimeMonitorService(
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
        service = RealtimeMonitorService(
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
        service = RealtimeMonitorService(
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
        service = RealtimeMonitorService(
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
                            "directional_efficiency_15b": 0.4,
                            "vwap_cross_count_15b": 1,
                            "tick_imbalance_5b": 0.2,
                            "trade_intensity_5b": 3,
                            "trade_intensity_ratio_30b": 1.0,
                            "range_ratio_5b_30b": 0.2,
                            "adx_14": 20.0,
                            "plus_di_14": 22.0,
                            "minus_di_14": 10.0,
                            "di_bias_14": 12.0,
                            "choppiness_14": 45.0,
                            "compression_score": 10,
                            "expansion_score": 65,
                            "compression_expansion_state": "expanding",
                            "session_cvd": 15.0,
                            "cvd_5b_delta": 7.0,
                            "cvd_15b_delta": 10.0,
                            "cvd_5b_slope": 2.0,
                            "price_cvd_divergence_15b": "none",
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
                            "directional_efficiency_15b": 0.6,
                            "vwap_cross_count_15b": 0,
                            "tick_imbalance_5b": 0.4,
                            "trade_intensity_5b": 5,
                            "trade_intensity_ratio_30b": 1.2,
                            "range_ratio_5b_30b": 0.3,
                            "adx_14": 24.0,
                            "plus_di_14": 25.0,
                            "minus_di_14": 9.0,
                            "di_bias_14": 16.0,
                            "choppiness_14": 38.0,
                            "compression_score": 5,
                            "expansion_score": 72,
                            "compression_expansion_state": "expanding",
                            "session_cvd": 28.0,
                            "cvd_5b_delta": 12.0,
                            "cvd_15b_delta": 18.0,
                            "cvd_5b_slope": 2.4,
                            "price_cvd_divergence_15b": "none",
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

    def test_run_cycle_includes_registry_stocks_in_metadata_and_subscription_log(self) -> None:
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
                "symbol": "MXFR1",
                "target_code": "MXFR1",
            },
        )()
        stock_contract = type(
            "StockContract",
            (),
            {
                "code": "2330",
                "symbol": "2330",
                "target_code": "",
            },
        )()
        ticks = [
            CanonicalTick(
                ts=datetime(2026, 4, 20, 9, 0, 1),
                trading_day=date(2026, 4, 20),
                symbol="2330",
                instrument_key="2330",
                contract_month=None,
                strike_price=None,
                call_put=None,
                session="day",
                price=950.0,
                size=1.0,
                tick_direction="up",
                source="shioaji_live",
            )
        ]
        store = DummyStore()
        logs = []
        service = RealtimeMonitorService(
            provider=StreamingProvider(
                ticks,
                [option_contract],
                underlying_contract,
                symbol_contracts={"2330": stock_contract, "MXFR1": underlying_contract},
            ),
            store=store,
            option_root="AUTO",
            expiry_count=2,
            atm_window=20,
            underlying_future_symbol="MXFR1",
            call_put="both",
            session_scope="day_and_night",
            batch_size=500,
            snapshot_interval_seconds=5.0,
            log_callback=logs.append,
            registry_path="config/symbols.csv",
            registry_stock_symbols=["2330"],
        )
        service.run_id = "test-run"

        service._run_cycle()

        started_runs = [run for run in store.live_runs if run.status == "started"]
        self.assertTrue(started_runs)
        self.assertIn('"2330"', started_runs[0].symbols_json)
        subscribed = next(item for item in logs if item["status"] == "subscribed")
        self.assertEqual(subscribed["registry_path"], "config/symbols.csv")
        self.assertEqual(subscribed["registry_stock_count"], 1)
        self.assertEqual(subscribed["registry_stock_symbols"], ["2330"])

    def test_live_series_merges_kronos_series_and_metadata(self) -> None:
        service = RealtimeMonitorService(
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
        service._snapshot_history.append(
            {
                "session_id": "test-run",
                "index": 0,
                "simulated_at": "2026-04-20T09:00:00",
                "snapshot": {"pressure_index": 5, "raw_pressure": 12, "regime": {}},
            }
        )
        service._kronos_series_history = {
            "mtx_up_50_in_10m_probability": [{"time": "2026-04-20T09:04:00", "value": 0.75}],
            "mtx_down_50_in_10m_probability": [{"time": "2026-04-20T09:04:00", "value": 0.25}],
            "mtx_expected_close_delta_10m": [{"time": "2026-04-20T09:04:00", "value": 18.0}],
        }
        service._kronos_status = "ready"

        series = service.live_series(
            [
                "pressure_index",
                "mtx_up_50_in_10m_probability",
                "mtx_down_50_in_10m_probability",
                "mtx_expected_close_delta_10m",
            ]
        )

        self.assertEqual(series["mtx_up_50_in_10m_probability"][0]["value"], 0.75)
        self.assertEqual(series["mtx_down_50_in_10m_probability"][0]["value"], 0.25)
        self.assertEqual(series["mtx_expected_close_delta_10m"][0]["value"], 18.0)

        metadata = service.live_metadata()
        self.assertIn("mtx_up_50_in_10m_probability", metadata["available_series"])
        self.assertEqual(metadata["kronos"]["status"], "ready")

    def test_kronos_live_inference_emits_only_core_series(self) -> None:
        class FakePredictor:
            def predict_paths(self, bars, **kwargs):
                return [
                    [[100, 151, 100, 118, 1, 118] for _ in range(10)],
                    [[100, 120, 49, 90, 1, 90] for _ in range(10)],
                ]

        service = RealtimeMonitorService(
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
            kronos_live_settings=KronosLiveSettings(
                predictor=FakePredictor(),
                lookback=2,
                targets=(ProbabilityTarget(minutes=10, points=50),),
                sample_count=2,
            ),
        )

        decision_time = datetime(2026, 4, 20, 9, 4)
        service._run_kronos_inference(
            decision_time,
            [
                Bar(
                    ts=datetime(2026, 4, 20, 9, 3),
                    trading_day=date(2026, 4, 20),
                    symbol="MTX",
                    contract_month="202604",
                    session="day",
                    open=20000.0,
                    high=20005.0,
                    low=19995.0,
                    close=20000.0,
                    volume=10.0,
                    open_interest=None,
                    source="test",
                ),
                Bar(
                    ts=decision_time,
                    trading_day=date(2026, 4, 20),
                    symbol="MTX",
                    contract_month="202604",
                    session="day",
                    open=20000.0,
                    high=20005.0,
                    low=19995.0,
                    close=20000.0,
                    volume=10.0,
                    open_interest=None,
                    source="test",
                ),
            ],
        )

        self.assertEqual(service._kronos_status, "ready")
        self.assertIn("mtx_up_50_in_10m_probability", service._kronos_latest_metrics)
        self.assertIn("mtx_down_50_in_10m_probability", service._kronos_latest_metrics)
        self.assertIn("mtx_expected_close_delta_10m", service._kronos_latest_metrics)
        self.assertNotIn("mtx_probability_ready", service._kronos_latest_metrics)
        self.assertNotIn("mtx_path_close_delta_p50_10m", service._kronos_latest_metrics)

    def test_kronos_live_inference_persists_json_and_updates_latest_snapshot(self) -> None:
        class FakePredictor:
            def predict_paths(self, bars, **kwargs):
                return [
                    [[100, 151, 100, 118, 1, 118] for _ in range(10)],
                    [[100, 120, 49, 90, 1, 90] for _ in range(10)],
                ]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "kronos-live.json"
            service = RealtimeMonitorService(
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
                kronos_live_settings=KronosLiveSettings(
                    predictor=FakePredictor(),
                    lookback=2,
                    targets=(ProbabilityTarget(minutes=10, points=50),),
                    sample_count=2,
                    output_path=str(output_path),
                ),
            )
            service.run_id = "live-test"
            service._snapshot_history.append(
                {
                    "session_id": "live-test",
                    "index": 0,
                    "simulated_at": "2026-04-20T09:00:00",
                    "snapshot": {
                        "generated_at": "2026-04-20T09:00:00",
                        "pressure_index": 5,
                        "raw_pressure": 12,
                        "regime": {},
                    },
                }
            )

            decision_time = datetime(2026, 4, 20, 9, 4)
            service._run_kronos_inference(
                decision_time,
                [
                    Bar(
                        ts=datetime(2026, 4, 20, 9, 3),
                        trading_day=date(2026, 4, 20),
                        symbol="MTX",
                        contract_month="202604",
                        session="day",
                        open=20000.0,
                        high=20005.0,
                        low=19995.0,
                        close=20000.0,
                        volume=10.0,
                        open_interest=None,
                        source="test",
                    ),
                    Bar(
                        ts=decision_time,
                        trading_day=date(2026, 4, 20),
                        symbol="MTX",
                        contract_month="202604",
                        session="day",
                        open=20000.0,
                        high=20005.0,
                        low=19995.0,
                        close=20000.0,
                        volume=10.0,
                        open_interest=None,
                        source="test",
                    ),
                ],
            )

            dated_output_path = Path(tmpdir) / "kronos-live-2026-04-20.json"
            self.assertTrue(dated_output_path.exists())
            payload = json.loads(dated_output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["metadata"]["mode"], "live")
            self.assertEqual(payload["metadata"]["run_id"], "live-test")
            self.assertIn("mtx_up_50_in_10m_probability", payload["series"])
            self.assertEqual(
                service._snapshot_history[-1]["snapshot"]["mtx_up_50_in_10m_probability"],
                service._kronos_latest_metrics["mtx_up_50_in_10m_probability"],
            )

    def test_kronos_live_starts_every_closed_minute(self) -> None:
        service = RealtimeMonitorService(
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
            kronos_live_settings=KronosLiveSettings(
                predictor=object(),
                lookback=2,
                targets=(ProbabilityTarget(minutes=10, points=50),),
                sample_count=2,
                interval_minutes=1,
            ),
        )
        service._underlying_domain_bars.extend(
            [
                Bar(
                    ts=datetime(2026, 4, 20, 8, 44) + timedelta(minutes=index),
                    trading_day=date(2026, 4, 20),
                    symbol="MTX",
                    contract_month="202604",
                    session="day",
                    open=20000.0,
                    high=20005.0,
                    low=19995.0,
                    close=20000.0,
                    volume=10.0,
                    open_interest=None,
                    source="test",
                )
                for index in range(2)
            ]
        )

        with patch("qt_platform.monitor.service.threading.Thread") as thread_cls:
            service._maybe_start_kronos_inference(datetime(2026, 4, 20, 8, 45))
            self.assertTrue(thread_cls.called)

        service._kronos_thread = None
        with patch("qt_platform.monitor.service.threading.Thread") as thread_cls:
            service._maybe_start_kronos_inference(datetime(2026, 4, 20, 8, 46))
            self.assertTrue(thread_cls.called)

    def test_kronos_live_also_starts_during_night_session(self) -> None:
        service = RealtimeMonitorService(
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
            kronos_live_settings=KronosLiveSettings(
                predictor=object(),
                lookback=2,
                targets=(ProbabilityTarget(minutes=10, points=50),),
                sample_count=2,
                interval_minutes=1,
            ),
        )
        service._underlying_domain_bars.extend(
            [
                Bar(
                    ts=datetime(2026, 4, 20, 21, 0) + timedelta(minutes=index),
                    trading_day=date(2026, 4, 20),
                    symbol="MTX",
                    contract_month="202604",
                    session="night",
                    open=20000.0,
                    high=20005.0,
                    low=19995.0,
                    close=20000.0,
                    volume=10.0,
                    open_interest=None,
                    source="test",
                )
                for index in range(2)
            ]
        )

        with patch("qt_platform.monitor.service.threading.Thread") as thread_cls:
            service._maybe_start_kronos_inference(datetime(2026, 4, 20, 21, 0))
            self.assertTrue(thread_cls.called)


if __name__ == "__main__":
    unittest.main()
