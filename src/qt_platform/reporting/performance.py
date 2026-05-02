from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any

from qt_platform.domain import BacktestResult

FILL_SUMMARY_FIELDS = [
    "ts",
    "side",
    "price",
    "size",
    "reason",
    "target_direction",
    "bias_direction",
    "pressure_index",
    "raw_pressure",
    "regime_state",
    "structure_state",
    "trend_quality_score",
    "trend_bias_state",
    "flow_impulse_score",
    "flow_state",
    "range_state",
]


def build_backtest_report_payload(result: BacktestResult, name: str) -> dict[str, Any]:
    return {
        "name": name,
        "generated_at": datetime.now().isoformat(),
        "starting_cash": result.starting_cash,
        "ending_cash": result.ending_cash,
        "metrics": result.metrics,
        "equity_curve": [
            {"ts": ts.isoformat(), "equity": equity}
            for ts, equity in result.equity_curve
        ],
        "fills": [
            {
                "ts": fill.ts.isoformat(),
                "side": fill.side.value,
                "price": fill.price,
                "size": fill.size,
                "reason": fill.reason,
                "metadata": fill.metadata,
            }
            for fill in result.fills
        ],
        "trades": [
            {
                "entry_ts": trade.entry_ts.isoformat(),
                "exit_ts": trade.exit_ts.isoformat(),
                "side": trade.side.value,
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "size": trade.size,
                "pnl": trade.pnl,
            }
            for trade in result.trades
        ],
    }


def write_json_report(result: BacktestResult, output_dir: str, name: str) -> Path:
    import json

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    target = Path(output_dir) / f"{name}.json"
    target.write_text(
        json.dumps(build_backtest_report_payload(result, name), indent=2),
        encoding="utf-8",
    )
    return target


def build_annotated_fill_summary_rows(result: BacktestResult) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for fill in result.fills:
        metadata = fill.metadata or {}
        rows.append(
            {
                "ts": fill.ts.isoformat(),
                "side": fill.side.value,
                "price": fill.price,
                "size": fill.size,
                "reason": fill.reason,
                "target_direction": _fill_metadata_value(metadata, "target_direction"),
                "bias_direction": _fill_metadata_value(metadata, "bias_direction"),
                "pressure_index": _fill_metadata_value(metadata, "pressure_index"),
                "raw_pressure": _fill_metadata_value(metadata, "raw_pressure"),
                "regime_state": _fill_metadata_value(metadata, "regime_state"),
                "structure_state": _fill_metadata_value(metadata, "structure_state"),
                "trend_quality_score": _fill_metadata_value(metadata, "trend_quality_score"),
                "trend_bias_state": _fill_metadata_value(metadata, "trend_bias_state"),
                "flow_impulse_score": _fill_metadata_value(metadata, "flow_impulse_score"),
                "flow_state": _fill_metadata_value(metadata, "flow_state"),
                "range_state": _fill_metadata_value(metadata, "range_state"),
            }
        )
    return rows


def write_annotated_fill_summary_csv(result: BacktestResult, output_dir: str, name: str) -> Path:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    target = Path(output_dir) / f"{name}-fills.csv"
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FILL_SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(build_annotated_fill_summary_rows(result))
    return target


def _fill_metadata_value(metadata: dict[str, Any], name: str) -> Any:
    indicator_values = metadata.get("indicator_values")
    if isinstance(indicator_values, dict) and name in indicator_values:
        return indicator_values[name]
    return metadata.get(name)


def write_html_report(result: BacktestResult, output_dir: str, name: str) -> Path:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    target = Path(output_dir) / f"{name}.html"
    json_target = Path(output_dir) / f"{name}.json"
    rows = "\n".join(
        f"<tr><td>{key}</td><td>{value}</td></tr>"
        for key, value in sorted(result.metrics.items())
    )
    html = f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>{name}</title>
    <style>
      body {{ font-family: sans-serif; margin: 2rem; }}
      table {{ border-collapse: collapse; }}
      td, th {{ border: 1px solid #ddd; padding: 0.5rem 0.75rem; }}
    </style>
  </head>
  <body>
    <h1>{name}</h1>
    <p>Starting cash: {result.starting_cash:.2f}</p>
    <p>Ending cash: {result.ending_cash:.2f}</p>
    <p>JSON report: <a href="{json_target.name}">{json_target.name}</a></p>
    <table>
      <thead><tr><th>Metric</th><th>Value</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </body>
</html>
"""
    target.write_text(html, encoding="utf-8")
    return target


def write_backtest_report_bundle(result: BacktestResult, output_dir: str, name: str) -> tuple[Path, Path]:
    json_report = write_json_report(result, output_dir, name)
    html_report = write_html_report(result, output_dir, name)
    return html_report, json_report
