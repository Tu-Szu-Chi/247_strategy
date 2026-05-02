from __future__ import annotations

import argparse
from datetime import datetime
import time

from qt_platform.cli.common import add_common_args, emit_status, get_database_url, new_live_run_id
from qt_platform.live.shioaji_provider import ShioajiLiveProvider
from qt_platform.live.universe import load_registry_stock_symbols
from qt_platform.monitor import KronosLiveSettings, MonitorReplayService, RealtimeMonitorService
from qt_platform.monitor.replay import load_external_indicator_series
from qt_platform.settings import Settings
from qt_platform.storage.factory import build_bar_repository
from qt_platform.web import build_option_power_app


def register_monitor_commands(subparsers):
    monitor_parser = subparsers.add_parser("monitor", help="Realtime monitoring and research")
    monitor_subparsers = monitor_parser.add_subparsers(dest="monitor_command", required=True)

    # Live command
    live = monitor_subparsers.add_parser("live", help="Start live monitoring")
    add_common_args(live)
    live.add_argument("--provider", default="shioaji")
    live.add_argument("--option-root", default="AUTO")
    live.add_argument("--expiry-count", type=int, default=2)
    live.add_argument("--atm-window", type=int, default=20)
    live.add_argument("--underlying-future-symbol", default="MXFR1")
    live.add_argument("--registry")
    live.add_argument("--call-put", default="both")
    live.add_argument("--batch-size", type=int, default=500)
    live.add_argument("--idle-timeout-seconds", type=float, default=30.0)
    live.add_argument("--simulation", action="store_true")
    live.add_argument("--session-scope", default="day_and_night")
    live.add_argument("--host", default="127.0.0.1")
    live.add_argument("--port", type=int, default=8000)
    live.add_argument("--snapshot-interval-seconds", type=float, default=10.0)
    live.add_argument("--ready-timeout-seconds", type=float, default=15.0)
    live.add_argument("--replay-underlying-symbol", default="MTX")
    live.add_argument("--kronos-live", action="store_true")
    live.add_argument("--log-file", default="logs/monitor-live.log")

    # Replay command
    replay = monitor_subparsers.add_parser("replay", help="Start replay session")
    add_common_args(replay)
    replay.add_argument("--start", required=True)
    replay.add_argument("--end", required=True)
    replay.add_argument("--option-root", default="AUTO")
    replay.add_argument("--expiry-count", type=int, default=2)
    replay.add_argument("--underlying-symbol", default="MTX")
    replay.add_argument("--host", default="127.0.0.1")
    replay.add_argument("--port", type=int, default=8000)
    replay.add_argument("--snapshot-interval-seconds", type=float, default=10.0)
    replay.add_argument("--kronos-series-json")
    replay.add_argument("--log-file", default="logs/monitor-replay.log")


def handle_monitor_command(args: argparse.Namespace, settings: Settings):
    if args.monitor_command == "live":
        _handle_live(args, settings)
    elif args.monitor_command == "replay":
        _handle_replay(args, settings)


def _handle_live(args: argparse.Namespace, settings: Settings):
    try:
        import uvicorn
    except ImportError:
        raise RuntimeError("uvicorn is required for monitor. Install with: pip install uvicorn")
    store = build_bar_repository(get_database_url(args, settings))
    registry_path = args.registry or settings.sync.registry_path
    registry_stock_symbols = load_registry_stock_symbols(registry_path)

    provider = ShioajiLiveProvider(
        settings=settings.shioaji,
        idle_timeout_seconds=args.idle_timeout_seconds,
        simulation=args.simulation,
    )
    
    kronos_live_settings = None
    if getattr(args, "kronos_live", False) or settings.kronos.enabled:
        from qt_platform.kronos.adapter import KronosModelConfig, KronosPathPredictor
        from qt_platform.kronos import parse_probability_target
        predictor = KronosPathPredictor(
            KronosModelConfig(
                model_id=settings.kronos.model,
                tokenizer_id=settings.kronos.tokenizer,
                device=settings.kronos.device,
            )
        )
        kronos_live_settings = KronosLiveSettings(
            predictor=predictor,
            lookback=settings.kronos.lookback,
            targets=tuple(parse_probability_target(t) for t in settings.kronos.target),
            sample_count=settings.kronos.sample_count,
            interval_minutes=settings.kronos.interval_minutes,
        )

    runtime = RealtimeMonitorService(
        provider=provider,
        store=store,
        option_root=args.option_root,
        expiry_count=args.expiry_count,
        atm_window=args.atm_window,
        underlying_future_symbol=args.underlying_future_symbol,
        registry_path=registry_path,
        registry_stock_symbols=registry_stock_symbols,
        call_put=args.call_put,
        session_scope=args.session_scope,
        batch_size=args.batch_size,
        snapshot_interval_seconds=args.snapshot_interval_seconds,
        log_callback=lambda payload: emit_status(payload, args.log_file),
        kronos_live_settings=kronos_live_settings,
    )
    
    replay = MonitorReplayService(
        store=store,
        option_root=args.option_root,
        expiry_count=args.expiry_count,
        underlying_symbol=args.replay_underlying_symbol,
        snapshot_interval_seconds=args.snapshot_interval_seconds,
    )
    
    run_id = new_live_run_id()
    runtime.start(run_id=run_id)
    if not runtime.wait_until_ready(timeout=args.ready_timeout_seconds):
        emit_status({"status": "error", "message": "Monitor service timed out during startup."}, args.log_file)
        return
        
    app = build_option_power_app(runtime_service=runtime, replay_service=replay)
    emit_status({"status": "web_ready", "url": f"http://{args.host}:{args.port}/"}, args.log_file)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info", access_log=False)


def _handle_replay(args: argparse.Namespace, settings: Settings):
    try:
        import uvicorn
    except ImportError:
        raise RuntimeError("uvicorn is required for monitor. Install with: pip install uvicorn")
    store = build_bar_repository(get_database_url(args, settings))
    external_indicator_series = load_external_indicator_series(args.kronos_series_json)
    replay = MonitorReplayService(
        store=store,
        option_root=args.option_root,
        expiry_count=args.expiry_count,
        underlying_symbol=args.underlying_symbol,
        snapshot_interval_seconds=args.snapshot_interval_seconds,
        external_indicator_series=external_indicator_series,
    )
    
    requested_start = datetime.fromisoformat(args.start)
    requested_end = datetime.fromisoformat(args.end)
    
    metadata = replay.create_session(
        start=requested_start,
        end=requested_end,
        set_as_default=True,
    )
    
    app = build_option_power_app(replay_service=replay)
    emit_status({"status": "replay_ready", "url": f"http://{args.host}:{args.port}/research"}, args.log_file)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info", access_log=False)
