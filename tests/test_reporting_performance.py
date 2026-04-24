import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from qt_platform.domain import BacktestResult, Fill, Side, Trade
from qt_platform.reporting.performance import (
    build_backtest_report_payload,
    write_backtest_report_bundle,
)


class ReportingPerformanceTest(unittest.TestCase):
    def test_build_backtest_report_payload_serializes_trade_data(self) -> None:
        result = BacktestResult(
            starting_cash=1000.0,
            ending_cash=1110.0,
            equity_curve=[(datetime(2026, 4, 20, 9, 0), 1000.0)],
            fills=[
                Fill(
                    ts=datetime(2026, 4, 20, 9, 1),
                    side=Side.BUY,
                    price=100.0,
                    size=1,
                    reason="entry",
                )
            ],
            trades=[
                Trade(
                    entry_ts=datetime(2026, 4, 20, 9, 1),
                    exit_ts=datetime(2026, 4, 20, 9, 2),
                    side=Side.BUY,
                    entry_price=100.0,
                    exit_price=110.0,
                    size=1,
                )
            ],
            metrics={"net_pnl": 110.0},
        )

        payload = build_backtest_report_payload(result, "mtx-backtest")

        self.assertEqual(payload["name"], "mtx-backtest")
        self.assertEqual(payload["fills"][0]["side"], "buy")
        self.assertEqual(payload["trades"][0]["pnl"], 10.0)
        self.assertEqual(payload["equity_curve"][0]["ts"], "2026-04-20T09:00:00")

    def test_write_backtest_report_bundle_writes_html_and_json(self) -> None:
        result = BacktestResult(
            starting_cash=1000.0,
            ending_cash=1050.0,
            equity_curve=[],
            fills=[],
            trades=[],
            metrics={"net_pnl": 50.0},
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            html_report, json_report = write_backtest_report_bundle(result, tmp_dir, "sample")

            self.assertTrue(Path(html_report).exists())
            self.assertTrue(Path(json_report).exists())
            payload = json.loads(Path(json_report).read_text(encoding="utf-8"))
            self.assertEqual(payload["metrics"]["net_pnl"], 50.0)
            self.assertIn("sample.json", Path(html_report).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
