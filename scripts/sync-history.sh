#!/bin/bash

set -euo pipefail

CONFIG_PATH="config/config.yaml"
REGISTRY_PATH="config/symbols.csv"
START_DATE="2026-04-18"
SYNC_TIME="08:59"
SESSION_SCOPE="day_and_night"
LOG_FILE="logs/history-sync.log"
DATABASE_URL=""
RUN_FOREVER=false

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --config) CONFIG_PATH="$2"; shift ;;
        --registry) REGISTRY_PATH="$2"; shift ;;
        --start-date) START_DATE="$2"; shift ;;
        --sync-time) SYNC_TIME="$2"; shift ;;
        --session-scope) SESSION_SCOPE="$2"; shift ;;
        --log-file) LOG_FILE="$2"; shift ;;
        --database-url) DATABASE_URL="$2"; shift ;;
        --run-forever) RUN_FOREVER=true ;;
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

REGISTRY_FULL_PATH="$REPO_ROOT/$REGISTRY_PATH"
if [[ ! -f "$REGISTRY_FULL_PATH" ]]; then
    echo "Error: Registry file not found: $REGISTRY_FULL_PATH"
    exit 1
fi

if ! [[ "$START_DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    echo "Error: --start-date must be in yyyy-MM-dd format: $START_DATE"
    exit 1
fi

if ! [[ "$SYNC_TIME" =~ ^[0-9]{2}:[0-9]{2}$ ]]; then
    echo "Error: --sync-time must be in HH:mm format: $SYNC_TIME"
    exit 1
fi

LOG_FULL_PATH="$REPO_ROOT/$LOG_FILE"
LOG_DIR="$(dirname "$LOG_FULL_PATH")"
mkdir -p "$LOG_DIR"

CLI_ARGS=(
    "-m" "qt_platform.cli.main"
    "--config" "$CONFIG_PATH"
    "history-sync"
    "--registry" "$REGISTRY_PATH"
    "--start-date" "$START_DATE"
    "--sync-time" "$SYNC_TIME"
    "--session-scope" "$SESSION_SCOPE"
    "--log-file" "$LOG_FILE"
)

if [[ -n "$DATABASE_URL" ]]; then
    CLI_ARGS+=("--database-url" "$DATABASE_URL")
fi

if [[ "$RUN_FOREVER" == true ]]; then
    CLI_ARGS+=("--run-forever")
fi

echo -e "\033[0;36mStarting history sync...\033[0m"
echo "Repo root: $REPO_ROOT"
echo "Config: $CONFIG_FULL_PATH"
echo "Registry: $REGISTRY_FULL_PATH"
echo "Start date: $START_DATE"
echo "Sync time: $SYNC_TIME"
echo "Run forever: $RUN_FOREVER"
echo "Log file: $LOG_FULL_PATH"

exec "$PYTHON_EXE" "${CLI_ARGS[@]}"
