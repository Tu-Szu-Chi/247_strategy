from __future__ import annotations

import argparse
import sys

from qt_platform.cli.backtest import register_backtest_commands, handle_backtest_command
from qt_platform.cli.data import register_data_commands, handle_data_command
from qt_platform.cli.kronos import register_kronos_commands, handle_kronos_command
from qt_platform.cli.monitor import register_monitor_commands, handle_monitor_command
from qt_platform.settings import load_settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="qt-platform")
    parser.add_argument("--config", default="config/config.yaml", help="Path to config.yaml")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Register subcommands
    register_monitor_commands(subparsers)
    register_data_commands(subparsers)
    register_backtest_commands(subparsers)
    register_kronos_commands(subparsers)

    args = parser.parse_args()
    settings = load_settings(args.config)

    try:
        if args.command == "monitor":
            handle_monitor_command(args, settings)
        elif args.command == "data":
            handle_data_command(args, settings)
        elif args.command == "backtest":
            handle_backtest_command(args, settings)
        elif args.command == "kronos":
            handle_kronos_command(args, settings)
    except Exception as e:
        print(f"Error: {e}")
        # In production, we might want to log the full traceback
        # import traceback
        # traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
