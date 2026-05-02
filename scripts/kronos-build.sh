#!/bin/bash

set -euo pipefail

CONFIG_PATH="config/config.yaml"
SYMBOL="MTX"
START="2026-04-30T08:45:00"
END="2026-05-01T00:30:00"
LOOKBACK=""
TARGET="10m:50"
SAMPLE_COUNT=""
OUTPUT="reports/mtx-probability.json"
DATABASE_URL=""

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --config) CONFIG_PATH="$2"; shift ;;
        --symbol) SYMBOL="$2"; shift ;;
        --start) START="$2"; shift ;;
        --end) END="$2"; shift ;;
        --lookback) LOOKBACK="$2"; shift ;;
        --target) TARGET="$2"; shift ;;
        --sample-count) SAMPLE_COUNT="$2"; shift ;;
        --output) OUTPUT="$2"; shift ;;
        --database-url) DATABASE_URL="$2"; shift ;;
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

CLI_ARGS=(
    "-m" "qt_platform.cli.main"
    "--config" "$CONFIG_PATH"
    "kronos" "probability"
    "--symbol" "$SYMBOL"
    "--start" "$START"
    "--end" "$END"
    "--target" "$TARGET"
    "--output" "$OUTPUT"
)

if [[ -n "$LOOKBACK" ]]; then
    CLI_ARGS+=("--lookback" "$LOOKBACK")
fi

if [[ -n "$SAMPLE_COUNT" ]]; then
    CLI_ARGS+=("--sample-count" "$SAMPLE_COUNT")
fi

if [[ -n "$DATABASE_URL" ]]; then
    CLI_ARGS+=("--database-url" "$DATABASE_URL")
fi

echo -e "\033[0;36mBuilding Kronos probability series...\033[0m"
echo "Repo root: $REPO_ROOT"
echo "Config: $CONFIG_FULL_PATH"
echo "Symbol: $SYMBOL"
echo "Start: $START"
echo "End: $END"
echo "Target: $TARGET"
echo "Output: $OUTPUT"

exec "$PYTHON_EXE" "${CLI_ARGS[@]}"
