from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from qt_platform.cli.common import add_common_args, get_database_url
from qt_platform.contracts import root_symbol_for, select_symbol_view
from qt_platform.kronos import (
    build_probability_indicator_series,
    parse_probability_target,
)
from qt_platform.kronos.adapter import KronosModelConfig, KronosPathPredictor
from qt_platform.settings import Settings
from qt_platform.storage.factory import build_bar_repository


def register_kronos_commands(subparsers):
    kronos_parser = subparsers.add_parser("kronos", help="AI prediction tasks")
    kronos_subparsers = kronos_parser.add_subparsers(dest="kronos_command", required=True)

    prob = kronos_subparsers.add_parser("probability", help="Build probability indicator series")
    add_common_args(prob)
    prob.add_argument("--symbol", default="MTX")
    prob.add_argument("--start", required=True)
    prob.add_argument("--end", required=True)
    prob.add_argument("--lookback", type=int)
    prob.add_argument("--target", action="append")
    prob.add_argument("--sample-count", type=int)
    prob.add_argument("--output")


def handle_kronos_command(args: argparse.Namespace, settings: Settings):
    if args.kronos_command == "probability":
        _handle_probability(args, settings)


def _handle_probability(args: argparse.Namespace, settings: Settings):
    store = build_bar_repository(get_database_url(args, settings))
    start = datetime.fromisoformat(args.start)
    end = datetime.fromisoformat(args.end)
    
    bars = store.list_bars(
        timeframe="1m",
        symbol=root_symbol_for(args.symbol),
        start=start,
        end=end,
    )
    bars = select_symbol_view(args.symbol, bars)
    
    # Building predictor from settings or args
    predictor = _build_predictor(args, settings)
    
    targets = [parse_probability_target(t) for t in (args.target or ["10m:50"])]
    
    series = build_probability_indicator_series(
        bars,
        predictor=predictor,
        lookback=args.lookback or settings.kronos.lookback,
        targets=targets,
        sample_count=args.sample_count or settings.kronos.sample_count,
    )
    
    if args.output:
        Path(args.output).write_text(json.dumps(series, indent=2, default=str))
        print(f"Saved to {args.output}")
    else:
        print(json.dumps(series, indent=2, default=str))


def _build_predictor(args, settings):
    return KronosPathPredictor(
        KronosModelConfig(
            model_id=settings.kronos.model,
            tokenizer_id=settings.kronos.tokenizer,
            device=settings.kronos.device,
        )
    )
