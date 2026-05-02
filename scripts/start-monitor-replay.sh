#!/bin/bash

set -euo pipefail

CONFIG_PATH="config/config.yaml"
START="2026-04-30T08:45:00"
END="2026-05-01T00:30:00"
OPTION_ROOT="AUTO"
EXPIRY_COUNT=2
UNDERLYING_SYMBOL="MTX"
LISTEN_HOST="127.0.0.1"
PORT=8000
SNAPSHOT_INTERVAL_SECONDS=10.0
LOG_FILE="logs/monitor-replay.log"
DATABASE_URL=""
KRONOS_JSON=""

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --config) CONFIG_PATH="$2"; shift ;;
        --start) START="$2"; shift ;;
        --end) END="$2"; shift ;;
        --option-root) OPTION_ROOT="$2"; shift ;;
        --expiry-count) EXPIRY_COUNT="$2"; shift ;;
        --underlying-symbol) UNDERLYING_SYMBOL="$2"; shift ;;
        --host) LISTEN_HOST="$2"; shift ;;
        --port) PORT="$2"; shift ;;
        --snapshot-interval-seconds) SNAPSHOT_INTERVAL_SECONDS="$2"; shift ;;
        --log-file) LOG_FILE="$2"; shift ;;
        --database-url) DATABASE_URL="$2"; shift ;;
        --kronos-series-json) KRONOS_JSON="$2"; shift ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

export PYTHONPATH="src"

PYTHON_EXE="$REPO_ROOT/.venv/bin/python"
if [[ ! -f "$PYTHON_EXE" ]]; then
    echo "Error: Python virtualenv not found: $PYTHON_EXE"
    exit 1
fi

CONFIG_FULL_PATH="$REPO_ROOT/$CONFIG_PATH"
if [[ ! -f "$CONFIG_FULL_PATH" ]]; then
    echo "Error: Config file not found: $CONFIG_FULL_PATH"
    exit 1
fi

LOG_FULL_PATH="$REPO_ROOT/$LOG_FILE"
LOG_DIR="$(dirname "$LOG_FULL_PATH")"
mkdir -p "$LOG_DIR"

CLI_ARGS=(
    "-m" "qt_platform.cli.main"
    "--config" "$CONFIG_PATH"
    "monitor" "replay"
    "--start" "$START"
    "--end" "$END"
    "--option-root" "$OPTION_ROOT"
    "--expiry-count" "$EXPIRY_COUNT"
    "--underlying-symbol" "$UNDERLYING_SYMBOL"
    "--host" "$LISTEN_HOST"
    "--port" "$PORT"
    "--snapshot-interval-seconds" "$SNAPSHOT_INTERVAL_SECONDS"
    "--log-file" "$LOG_FILE"
)

if [[ -n "$DATABASE_URL" ]]; then
    CLI_ARGS+=("--database-url" "$DATABASE_URL")
fi

if [[ -n "$KRONOS_JSON" ]]; then
    CLI_ARGS+=("--kronos-series-json" "$KRONOS_JSON")
fi

echo -e "\033[0;36mStarting monitor replay web...\033[0m"
echo "Repo root: $REPO_ROOT"
echo "Config: $CONFIG_FULL_PATH"
echo "Start: $START"
echo "End: $END"
echo "Host: $LISTEN_HOST"
echo "Port: $PORT"
echo "Research Replay URL: http://$LISTEN_HOST:$PORT/research/replay"
echo "Log file: $LOG_FULL_PATH"

exec "$PYTHON_EXE" "${CLI_ARGS[@]}"
