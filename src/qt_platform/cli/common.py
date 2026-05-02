from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from qt_platform.settings import Settings


def add_common_args(parser: argparse.ArgumentParser):
    parser.add_argument("--database-url", help="Database URL (overrides config)")


def get_database_url(args: argparse.Namespace, settings: Settings) -> str:
    return args.database_url or settings.database.url


def emit_status(payload: dict, log_file: str | None = None) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    if not log_file:
        return
    path = Path(log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, default=str))
        fh.write(os.linesep)


def new_live_run_id() -> str:
    from uuid import uuid4
    return f"live-{datetime.now().strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}"
