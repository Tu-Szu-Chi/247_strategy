import json
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from qt_platform.live.recorder import LiveRecorderService, aggregate_ticks_to_bars
from qt_platform.live.stub_provider import StubLiveProvider
from qt_platform.storage.bar_store import SQLiteBarStore


class LiveRecorderTest(unittest.TestCase):
    def test_aggregate_ticks_to_bars_counts_up_and_down_ticks(self) -> None:
        with TemporaryDirectory() as temp_dir:
            ticks_path = Path(temp_dir) / "ticks.jsonl"
            ticks_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "ts": "2025-04-11T09:01:01",
                                "trading_day": "2025-04-11",
                                "symbol": "TXO",
                                "instrument_key": "TXO:202504W2:18000:call",
                                "contract_month": "202504W2",
                                "strike_price": 18000.0,
                                "call_put": "call",
                                "session": "day",
                                "price": 12.0,
                                "size": 1,
                                "tick_direction": "up",
                                "source": "stub_live",
                            }
                        ),
                        json.dumps(
                            {
                                "ts": "2025-04-11T09:01:20",
                                "trading_day": "2025-04-11",
                                "symbol": "TXO",
                                "instrument_key": "TXO:202504W2:18000:call",
                                "contract_month": "202504W2",
                                "strike_price": 18000.0,
                                "call_put": "call",
                                "session": "day",
                                "price": 15.0,
                                "size": 2,
                                "tick_direction": "down",
                                "source": "stub_live",
                            }
                        ),
                    ]
                )
            )
            provider = StubLiveProvider(ticks_path)
            provider.connect()
            ticks = list(provider.stream_ticks(["TXO"]))
            provider.close()

        bars = aggregate_ticks_to_bars(ticks)
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].open, 12.0)
        self.assertEqual(bars[0].close, 15.0)
        self.assertEqual(bars[0].volume, 3.0)
        self.assertEqual(bars[0].up_ticks, 1)
        self.assertEqual(bars[0].down_ticks, 1)

    def test_record_live_stub_persists_ticks_and_bars(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = f"{temp_dir}/bars.db"
            ticks_path = Path(temp_dir) / "ticks.jsonl"
            ticks_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "ts": "2025-04-11T09:01:01",
                                "trading_day": "2025-04-11",
                                "symbol": "TXO",
                                "instrument_key": "TXO:202504W2:18000:call",
                                "contract_month": "202504W2",
                                "strike_price": 18000.0,
                                "call_put": "call",
                                "session": "day",
                                "price": 12.0,
                                "size": 1,
                                "tick_direction": "up",
                                "source": "stub_live",
                            }
                        ),
                        json.dumps(
                            {
                                "ts": "2025-04-11T09:01:20",
                                "trading_day": "2025-04-11",
                                "symbol": "TXO",
                                "instrument_key": "TXO:202504W2:18000:call",
                                "contract_month": "202504W2",
                                "strike_price": 18000.0,
                                "call_put": "call",
                                "session": "day",
                                "price": 15.0,
                                "size": 2,
                                "tick_direction": "down",
                                "source": "stub_live",
                            }
                        ),
                    ]
                )
            )
            store = SQLiteBarStore(db_path)
            service = LiveRecorderService(provider=StubLiveProvider(ticks_path), store=store)

            result = service.record(symbols=["TXO"], run_id="test-run")
            raw_ticks = store.list_ticks("TXO", datetime(2025, 4, 11, 9, 1), datetime(2025, 4, 11, 9, 2))
            bars = store.list_bars("1m", "TXO", datetime(2025, 4, 11, 9, 1), datetime(2025, 4, 11, 9, 2))
            features = store.list_minute_force_features(
                symbol="TXO",
                start=datetime(2025, 4, 11, 9, 1),
                end=datetime(2025, 4, 11, 9, 2),
                run_id="test-run",
            )

        self.assertEqual(result.run_id, "test-run")
        self.assertEqual(result.ticks_appended, 2)
        self.assertEqual(result.bars_upserted, 1)
        self.assertEqual(len(raw_ticks), 2)
        self.assertEqual(len(bars), 1)
        self.assertEqual(len(features), 1)
        self.assertEqual(bars[0].up_ticks, 1)
        self.assertEqual(bars[0].down_ticks, 1)
        self.assertEqual(features[0].run_id, "test-run")
        self.assertEqual(features[0].tick_total, 2)


if __name__ == "__main__":
    unittest.main()
