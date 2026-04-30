#!/bin/bash

# Default parameters
CONFIG_PATH="config/config.yaml"
UNDERLYING_FUTURE_SYMBOL="MXFR1"
REPLAY_UNDERLYING_SYMBOL="MTX"
EXPIRY_COUNT=2
ATM_WINDOW=20
CALL_PUT="both"
SESSION_SCOPE="day_and_night"
LISTEN_HOST="127.0.0.1"
PORT=8000
SNAPSHOT_INTERVAL_SECONDS=10.0
READY_TIMEOUT_SECONDS=15.0
LOG_FILE="logs/serve-option-power.log"
DATABASE_URL=""
SIMULATION=false

# Parse arguments (optional, if you want to override defaults like in PowerShell)
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --config) CONFIG_PATH="$2"; shift ;;
        --underlying-future-symbol) UNDERLYING_FUTURE_SYMBOL="$2"; shift ;;
        --replay-underlying-symbol) REPLAY_UNDERLYING_SYMBOL="$2"; shift ;;
        --expiry-count) EXPIRY_COUNT="$2"; shift ;;
        --atm-window) ATM_WINDOW="$2"; shift ;;
        --call-put) CALL_PUT="$2"; shift ;;
        --session-scope) SESSION_SCOPE="$2"; shift ;;
        --host) LISTEN_HOST="$2"; shift ;;
        --port) PORT="$2"; shift ;;
        --snapshot-interval-seconds) SNAPSHOT_INTERVAL_SECONDS="$2"; shift ;;
        --ready-timeout-seconds) READY_TIMEOUT_SECONDS="$2"; shift ;;
        --log-file) LOG_FILE="$2"; shift ;;
        --database-url) DATABASE_URL="$2"; shift ;;
        --simulation) SIMULATION=true ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

# Resolve Repo Root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

export PYTHONPATH="src"

# macOS/Linux venv path
PYTHON_EXE="$REPO_ROOT/.venv/bin/python"
if [ ! -f "$PYTHON_EXE" ]; then
    echo "Error: Python virtualenv not found: $PYTHON_EXE"
    exit 1
fi

CONFIG_FULL_PATH="$REPO_ROOT/$CONFIG_PATH"
if [ ! -f "$CONFIG_FULL_PATH" ]; then
    echo "Error: Config file not found: $CONFIG_FULL_PATH"
    exit 1
fi

LOG_FULL_PATH="$REPO_ROOT/$LOG_FILE"
LOG_DIR="$(dirname "$LOG_FULL_PATH")"
mkdir -p "$LOG_DIR"

CLI_ARGS=(
    "-m" "qt_platform.cli.main"
    "--config" "$CONFIG_PATH"
    "serve-option-power"
    "--expiry-count" "$EXPIRY_COUNT"
    "--atm-window" "$ATM_WINDOW"
    "--underlying-future-symbol" "$UNDERLYING_FUTURE_SYMBOL"
    "--replay-underlying-symbol" "$REPLAY_UNDERLYING_SYMBOL"
    "--call-put" "$CALL_PUT"
    "--session-scope" "$SESSION_SCOPE"
    "--host" "$LISTEN_HOST"
    "--port" "$PORT"
    "--snapshot-interval-seconds" "$SNAPSHOT_INTERVAL_SECONDS"
    "--ready-timeout-seconds" "$READY_TIMEOUT_SECONDS"
    "--log-file" "$LOG_FILE"
)

if [ "$SIMULATION" = true ]; then
    CLI_ARGS+=("--simulation")
fi

if [ -n "$DATABASE_URL" ]; then
    CLI_ARGS+=("--database-url" "$DATABASE_URL")
fi

echo -e "\033[0;36mStarting option power web...\033[0m"
echo "Repo root: $REPO_ROOT"
echo "Config: $CONFIG_FULL_PATH"
echo "Live underlying future symbol: $UNDERLYING_FUTURE_SYMBOL"
echo "Replay underlying symbol: $REPLAY_UNDERLYING_SYMBOL"
echo "Option roots: AUTO nearest $EXPIRY_COUNT"
echo "ATM window: $ATM_WINDOW"
echo "Host: $LISTEN_HOST"
echo "Port: $PORT"
echo "Research Live URL: http://$LISTEN_HOST:$PORT/research/live"
echo "Research Replay URL: http://$LISTEN_HOST:$PORT/research/replay"
echo "Log file: $LOG_FULL_PATH"

exec "$PYTHON_EXE" "${CLI_ARGS[@]}"
