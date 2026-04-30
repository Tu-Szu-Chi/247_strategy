import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from qt_platform.domain import BacktestResult, Fill, Side, Trade
from qt_platform.reporting.performance import (
    build_annotated_fill_summary_rows,
    build_backtest_report_payload,
    write_annotated_fill_summary_csv,
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
                    metadata={
                        "signal_state": 1,
                        "indicator_values": {"signal_state": 1, "pressure_index": 63.0},
                    },
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
        self.assertEqual(payload["fills"][0]["metadata"]["indicator_values"]["pressure_index"], 63.0)
        self.assertEqual(payload["trades"][0]["pnl"], 10.0)
        self.assertEqual(payload["equity_curve"][0]["ts"], "2026-04-20T09:00:00")

    def test_annotated_fill_summary_flattens_indicator_metadata(self) -> None:
        result = BacktestResult(
            starting_cash=1000.0,
            ending_cash=990.0,
            equity_curve=[],
            fills=[
                Fill(
                    ts=datetime(2026, 4, 20, 9, 1),
                    side=Side.SELL,
                    price=100.0,
                    size=1,
                    reason="option_power_signal_short",
                    metadata={
                        "signal_state": -1,
                        "bias_signal": -1,
                        "target_direction": -1,
                        "bias_direction": -1,
                        "indicator_values": {
                            "pressure_index": 0.0,
                            "raw_pressure": 7.0,
                            "regime_state": -1,
                            "structure_state": -1,
                        },
                    },
                )
            ],
            trades=[],
            metrics={},
        )

        rows = build_annotated_fill_summary_rows(result)

        self.assertEqual(rows[0]["ts"], "2026-04-20T09:01:00")
        self.assertEqual(rows[0]["side"], "sell")
        self.assertEqual(rows[0]["signal_state"], -1)
        self.assertEqual(rows[0]["pressure_index"], 0.0)
        self.assertEqual(rows[0]["raw_pressure"], 7.0)

    def test_write_annotated_fill_summary_csv_writes_compact_rows(self) -> None:
        result = BacktestResult(
            starting_cash=1000.0,
            ending_cash=1000.0,
            equity_curve=[],
            fills=[
                Fill(
                    ts=datetime(2026, 4, 20, 9, 1),
                    side=Side.BUY,
                    price=100.0,
                    size=1,
                    reason="entry",
                    metadata={"signal_state": 1, "indicator_values": {"pressure_index": 63.0}},
                )
            ],
            trades=[],
            metrics={},
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            target = write_annotated_fill_summary_csv(result, tmp_dir, "sample")

            text = Path(target).read_text(encoding="utf-8")
            self.assertIn("ts,side,price,size,reason,signal_state", text)
            self.assertIn("2026-04-20T09:01:00,buy,100.0,1,entry,1", text)

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
