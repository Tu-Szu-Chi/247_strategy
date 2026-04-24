import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from qt_platform.cli.main import _serve_option_power


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
        )

        runtime = MagicMock()
        runtime.wait_until_ready.return_value = True
        runtime.status = "running"
        uvicorn_run = MagicMock()

        with patch("qt_platform.cli.main.ShioajiLiveProvider"), patch(
            "qt_platform.cli.main.build_bar_repository"
        ) as build_store, patch(
            "qt_platform.cli.main.OptionPowerRuntimeService", return_value=runtime
        ), patch(
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
        )

        runtime = MagicMock()
        runtime.wait_until_ready.return_value = True
        runtime.status = "connecting"
        uvicorn_run = MagicMock()

        with patch("qt_platform.cli.main.ShioajiLiveProvider"), patch(
            "qt_platform.cli.main.build_bar_repository"
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


if __name__ == "__main__":
    unittest.main()
