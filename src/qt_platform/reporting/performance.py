from __future__ import annotations

from pathlib import Path

from qt_platform.domain import BacktestResult


def write_html_report(result: BacktestResult, output_dir: str, name: str) -> Path:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    target = Path(output_dir) / f"{name}.html"
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
    <table>
      <thead><tr><th>Metric</th><th>Value</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </body>
</html>
"""
    target.write_text(html)
    return target

