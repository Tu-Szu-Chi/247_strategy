import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from qt_platform.cli.main import _serve_option_power, _serve_option_power_replay


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
        )
        settings = SimpleNamespace(
            shioaji=SimpleNamespace(),
            database=SimpleNamespace(url="sqlite:///tmp/test.db"),
            sync=SimpleNamespace(registry_path="config/symbols.csv"),
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
        )
        settings = SimpleNamespace(
            shioaji=SimpleNamespace(),
            database=SimpleNamespace(url="sqlite:///tmp/test.db"),
            sync=SimpleNamespace(registry_path="config/symbols.csv"),
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
