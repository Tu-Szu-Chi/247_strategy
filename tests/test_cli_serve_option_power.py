import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from qt_platform.cli.main import _serve_option_power, _serve_option_power_replay
from qt_platform.option_power.service import KronosLiveSettings


class ServeOptionPowerTest(unittest.TestCase):
    def test_serve_option_power_disables_uvicorn_access_log(self) -> None:
        args = SimpleNamespace(
            provider="shioaji",
            idle_timeout_seconds=30.0,
            simulation=True,
            database_url="sqlite:///tmp/test.db",
            option_root="AUTO",
            expiry_count=2,
            atm_window=20,
            underlying_future_symbol="MXFR1",
            registry=None,
            call_put="both",
            session_scope="day_and_night",
            batch_size=500,
            snapshot_interval_seconds=5.0,
            replay_underlying_symbol="MTX",
            log_file=None,
            ready_timeout_seconds=15.0,
            host="127.0.0.1",
            port=8000,
            kronos_live=False,
            kronos_output=None,
        )
        settings = SimpleNamespace(
            shioaji=SimpleNamespace(),
            database=SimpleNamespace(url="sqlite:///tmp/test.db"),
            sync=SimpleNamespace(registry_path="config/symbols.csv"),
            kronos=SimpleNamespace(
                enabled=False,
                target=["10m:50"],
                lookback=32,
                sample_count=4,
                interval_minutes=5,
                temperature=1.0,
                top_k=0,
                top_p=0.9,
                model="NeoQuasar/Kronos-mini",
                tokenizer="NeoQuasar/Kronos-Tokenizer-2k",
                model_revision=None,
                tokenizer_revision=None,
                device=None,
                max_context=512,
                output_path=None,
            ),
        )

        runtime = MagicMock()
        runtime.wait_until_ready.return_value = True
        runtime.status = "running"
        uvicorn_run = MagicMock()

        with patch("qt_platform.cli.main.ShioajiLiveProvider"), patch(
            "qt_platform.cli.main.build_bar_repository"
        ) as build_store, patch(
            "qt_platform.cli.main.load_registry_stock_symbols", return_value=["2330"]
        ) as load_registry_stock_symbols, patch(
            "qt_platform.cli.main.OptionPowerRuntimeService", return_value=runtime
        ) as runtime_service_cls, patch(
            "qt_platform.cli.main.OptionPowerReplayService"
        ) as replay_service, patch(
            "qt_platform.cli.main.build_option_power_app", return_value=object()
        ) as build_app, patch(
            "qt_platform.cli.main._emit_runtime_status"
        ), patch.dict(
            sys.modules, {"uvicorn": types.SimpleNamespace(run=uvicorn_run)}
        ):
            _serve_option_power(args, settings)

        self.assertEqual(uvicorn_run.call_args.kwargs["access_log"], False)
        load_registry_stock_symbols.assert_called_once_with("config/symbols.csv")
        self.assertEqual(
            runtime_service_cls.call_args.kwargs["registry_stock_symbols"],
            ["2330"],
        )
        replay_service.assert_called_once_with(
            store=build_store.return_value,
            option_root="AUTO",
            expiry_count=2,
            underlying_symbol="MTX",
            snapshot_interval_seconds=5.0,
        )
        self.assertIs(build_app.call_args.kwargs["runtime_service"], runtime)
        self.assertIs(build_app.call_args.kwargs["replay_service"], replay_service.return_value)

    def test_serve_option_power_allows_runtime_retry_states(self) -> None:
        args = SimpleNamespace(
            provider="shioaji",
            idle_timeout_seconds=30.0,
            simulation=True,
            database_url="sqlite:///tmp/test.db",
            option_root="AUTO",
            expiry_count=2,
            atm_window=20,
            underlying_future_symbol="MXFR1",
            registry=None,
            call_put="both",
            session_scope="day_and_night",
            batch_size=500,
            snapshot_interval_seconds=5.0,
            replay_underlying_symbol="MTX",
            log_file=None,
            ready_timeout_seconds=15.0,
            host="127.0.0.1",
            port=8000,
            kronos_live=False,
            kronos_output=None,
        )
        settings = SimpleNamespace(
            shioaji=SimpleNamespace(),
            database=SimpleNamespace(url="sqlite:///tmp/test.db"),
            sync=SimpleNamespace(registry_path="config/symbols.csv"),
            kronos=SimpleNamespace(
                enabled=False,
                target=["10m:50"],
                lookback=32,
                sample_count=4,
                interval_minutes=5,
                temperature=1.0,
                top_k=0,
                top_p=0.9,
                model="NeoQuasar/Kronos-mini",
                tokenizer="NeoQuasar/Kronos-Tokenizer-2k",
                model_revision=None,
                tokenizer_revision=None,
                device=None,
                max_context=512,
                output_path=None,
            ),
        )

        runtime = MagicMock()
        runtime.wait_until_ready.return_value = True
        runtime.status = "connecting"
        uvicorn_run = MagicMock()

        with patch("qt_platform.cli.main.ShioajiLiveProvider"), patch(
            "qt_platform.cli.main.build_bar_repository"
        ), patch(
            "qt_platform.cli.main.load_registry_stock_symbols", return_value=[]
        ), patch(
            "qt_platform.cli.main.OptionPowerRuntimeService", return_value=runtime
        ), patch(
            "qt_platform.cli.main.OptionPowerReplayService"
        ), patch(
            "qt_platform.cli.main.build_option_power_app", return_value=object()
        ), patch(
            "qt_platform.cli.main._emit_runtime_status"
        ), patch.dict(
            sys.modules, {"uvicorn": types.SimpleNamespace(run=uvicorn_run)}
        ):
            _serve_option_power(args, settings)

        self.assertTrue(uvicorn_run.called)

    def test_serve_option_power_can_enable_kronos_live(self) -> None:
        args = SimpleNamespace(
            provider="shioaji",
            idle_timeout_seconds=30.0,
            simulation=True,
            database_url="sqlite:///tmp/test.db",
            option_root="AUTO",
            expiry_count=2,
            atm_window=20,
            underlying_future_symbol="MXFR1",
            registry=None,
            call_put="both",
            session_scope="day_and_night",
            batch_size=500,
            snapshot_interval_seconds=5.0,
            replay_underlying_symbol="MTX",
            log_file=None,
            ready_timeout_seconds=15.0,
            host="127.0.0.1",
            port=8000,
            kronos_live=True,
            kronos_target=None,
            kronos_lookback=32,
            kronos_sample_count=4,
            kronos_interval_minutes=5,
            kronos_temperature=1.0,
            kronos_top_k=0,
            kronos_top_p=0.9,
            kronos_model="NeoQuasar/Kronos-mini",
            kronos_tokenizer="NeoQuasar/Kronos-Tokenizer-2k",
            kronos_model_revision=None,
            kronos_tokenizer_revision=None,
            kronos_device=None,
            kronos_max_context=512,
            kronos_output=None,
        )
        settings = SimpleNamespace(
            shioaji=SimpleNamespace(),
            database=SimpleNamespace(url="sqlite:///tmp/test.db"),
            sync=SimpleNamespace(registry_path="config/symbols.csv"),
            kronos=SimpleNamespace(
                enabled=False,
                target=["10m:50"],
                lookback=16,
                sample_count=2,
                interval_minutes=15,
                temperature=0.7,
                top_k=5,
                top_p=0.8,
                model="config-model",
                tokenizer="config-tokenizer",
                model_revision="rev-a",
                tokenizer_revision="rev-b",
                device="cuda:0",
                max_context=1024,
                output_path="reports/kronos-live-latest.json",
            ),
        )

        runtime = MagicMock()
        runtime.wait_until_ready.return_value = True
        runtime.status = "running"
        uvicorn_run = MagicMock()
        predictor = object()

        with patch("qt_platform.cli.main.ShioajiLiveProvider"), patch(
            "qt_platform.cli.main.build_bar_repository"
        ), patch(
            "qt_platform.cli.main.load_registry_stock_symbols", return_value=[]
        ), patch(
            "qt_platform.cli.main._build_kronos_path_predictor_with_prefix", return_value=predictor
        ), patch(
            "qt_platform.cli.main.OptionPowerRuntimeService", return_value=runtime
        ) as runtime_service_cls, patch(
            "qt_platform.cli.main.OptionPowerReplayService"
        ), patch(
            "qt_platform.cli.main.build_option_power_app", return_value=object()
        ), patch(
            "qt_platform.cli.main._emit_runtime_status"
        ), patch.dict(
            sys.modules, {"uvicorn": types.SimpleNamespace(run=uvicorn_run)}
        ):
            _serve_option_power(args, settings)

        self.assertIsInstance(
            runtime_service_cls.call_args.kwargs["kronos_live_settings"],
            KronosLiveSettings,
        )

    def test_serve_option_power_can_enable_kronos_live_from_config(self) -> None:
        args = SimpleNamespace(
            provider="shioaji",
            idle_timeout_seconds=30.0,
            simulation=True,
            database_url="sqlite:///tmp/test.db",
            option_root="AUTO",
            expiry_count=2,
            atm_window=20,
            underlying_future_symbol="MXFR1",
            registry=None,
            call_put="both",
            session_scope="day_and_night",
            batch_size=500,
            snapshot_interval_seconds=5.0,
            replay_underlying_symbol="MTX",
            log_file=None,
            ready_timeout_seconds=15.0,
            host="127.0.0.1",
            port=8000,
            kronos_live=False,
            kronos_target=None,
            kronos_lookback=None,
            kronos_sample_count=None,
            kronos_interval_minutes=None,
            kronos_temperature=None,
            kronos_top_k=None,
            kronos_top_p=None,
            kronos_model=None,
            kronos_tokenizer=None,
            kronos_model_revision=None,
            kronos_tokenizer_revision=None,
            kronos_device=None,
            kronos_max_context=None,
            kronos_output=None,
        )
        settings = SimpleNamespace(
            shioaji=SimpleNamespace(),
            database=SimpleNamespace(url="sqlite:///tmp/test.db"),
            sync=SimpleNamespace(registry_path="config/symbols.csv"),
            kronos=SimpleNamespace(
                enabled=True,
                target=["10m:50", "20m:100"],
                lookback=300,
                sample_count=128,
                interval_minutes=5,
                temperature=1.0,
                top_k=0,
                top_p=0.9,
                model="config-model",
                tokenizer="config-tokenizer",
                model_revision="rev-a",
                tokenizer_revision="rev-b",
                device="cuda:0",
                max_context=1024,
                output_path="reports/kronos-live-latest.json",
            ),
        )

        runtime = MagicMock()
        runtime.wait_until_ready.return_value = True
        runtime.status = "running"
        uvicorn_run = MagicMock()
        predictor = object()

        with patch("qt_platform.cli.main.ShioajiLiveProvider"), patch(
            "qt_platform.cli.main.build_bar_repository"
        ), patch(
            "qt_platform.cli.main.load_registry_stock_symbols", return_value=[]
        ), patch(
            "qt_platform.cli.main._build_kronos_path_predictor_with_prefix", return_value=predictor
        ) as build_predictor, patch(
            "qt_platform.cli.main.OptionPowerRuntimeService", return_value=runtime
        ) as runtime_service_cls, patch(
            "qt_platform.cli.main.OptionPowerReplayService"
        ), patch(
            "qt_platform.cli.main.build_option_power_app", return_value=object()
        ), patch(
            "qt_platform.cli.main._emit_runtime_status"
        ), patch.dict(
            sys.modules, {"uvicorn": types.SimpleNamespace(run=uvicorn_run)}
        ):
            _serve_option_power(args, settings)

        build_predictor.assert_called_once()
        kronos_live_settings = runtime_service_cls.call_args.kwargs["kronos_live_settings"]
        self.assertIsInstance(kronos_live_settings, KronosLiveSettings)
        self.assertEqual(kronos_live_settings.lookback, 300)
        self.assertEqual(kronos_live_settings.sample_count, 128)
        self.assertEqual(kronos_live_settings.interval_minutes, 5)
        self.assertEqual(kronos_live_settings.top_p, 0.9)
        self.assertEqual(kronos_live_settings.output_path, "reports/kronos-live-latest.json")

    def test_serve_option_power_replay_loads_kronos_series_json(self) -> None:
        args = SimpleNamespace(
            database_url="sqlite:///tmp/test.db",
            option_root="AUTO",
            expiry_count=2,
            underlying_symbol="MTX",
            host="127.0.0.1",
            port=8000,
            snapshot_interval_seconds=60.0,
            start="2026-04-14T09:00:00",
            end="2026-04-14T09:30:00",
            kronos_series_json="reports/kronos.json",
            log_file=None,
        )
        settings = SimpleNamespace(database=SimpleNamespace(url="sqlite:///tmp/test.db"))
        replay = MagicMock()
        replay.create_session.return_value = {
            "session_id": "replay-1",
            "snapshot_count": 3,
            "selected_option_roots": [],
            "underlying_symbol": "MTX",
            "start": args.start,
            "end": args.end,
        }
        store = MagicMock()
        store.bar_time_bounds.return_value = None
        uvicorn_run = MagicMock()

        with patch("qt_platform.cli.main.build_bar_repository", return_value=store), patch(
            "qt_platform.cli.main.load_external_indicator_series",
            return_value={"mtx_up_50_in_10m_probability": []},
        ) as load_external, patch(
            "qt_platform.cli.main.OptionPowerReplayService",
            return_value=replay,
        ) as replay_service_cls, patch(
            "qt_platform.cli.main.build_option_power_app",
            return_value=object(),
        ), patch(
            "qt_platform.cli.main._emit_runtime_status"
        ), patch.dict(
            sys.modules, {"uvicorn": types.SimpleNamespace(run=uvicorn_run)}
        ):
            _serve_option_power_replay(args, settings)

        load_external.assert_called_once_with("reports/kronos.json")
        self.assertEqual(
            replay_service_cls.call_args.kwargs["external_indicator_series"],
            {"mtx_up_50_in_10m_probability": []},
        )
        self.assertTrue(uvicorn_run.called)


if __name__ == "__main__":
    unittest.main()
