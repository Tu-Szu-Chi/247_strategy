import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from qt_platform.csv_import import import_csv_file, import_csv_folder
from qt_platform.storage.bar_store import SQLiteBarStore


class CsvImportTest(unittest.TestCase):
    def test_import_csv_file_for_stock(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = f"{temp_dir}/bars.db"
            csv_path = Path(temp_dir) / "2330.csv"
            csv_path.write_text(
                "\n".join(
                    [
                        "Symbol,Date,Time,Open,High,Low,Close,TotalVolume,UpTicks,DownTicks",
                        "2330,2025/4/11,09:01:00,848,848,840,842,9801,178,176",
                        "2330,2025/4/11,09:02:00,842,843,837,837,1393,114,117",
                    ]
                )
            )
            store = SQLiteBarStore(db_path)

            result = import_csv_file(store, csv_path)
            rows = store.list_bars("1m", "2330", datetime(2025, 4, 11, 9, 1), datetime(2025, 4, 11, 9, 2))

        self.assertEqual(result.rows_read, 2)
        self.assertEqual(result.upserted_bars, 2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].instrument_key, "2330")
        self.assertEqual(rows[0].contract_month, "")
        self.assertEqual(rows[0].up_ticks, 178.0)
        self.assertEqual(rows[0].down_ticks, 176.0)

    def test_import_csv_file_for_index_uses_prefixed_instrument_key(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = f"{temp_dir}/bars.db"
            csv_path = Path(temp_dir) / "TWOTC.csv"
            csv_path.write_text(
                "\n".join(
                    [
                        "Symbol,Date,Time,Open,High,Low,Close,TotalVolume",
                        "TWOTC,2025/4/11,09:01:00,200.39,200.39,195.88,195.88,368578",
                    ]
                )
            )
            store = SQLiteBarStore(db_path)

            result = import_csv_file(store, csv_path)
            rows = store.list_bars("1m", "TWOTC", datetime(2025, 4, 11, 9, 1), datetime(2025, 4, 11, 9, 1))

        self.assertEqual(result.upserted_bars, 1)
        self.assertEqual(rows[0].instrument_key, "index:TWOTC")
        self.assertEqual(rows[0].contract_month, "")
        self.assertIsNone(rows[0].up_ticks)
        self.assertIsNone(rows[0].down_ticks)

    def test_import_csv_folder_imports_multiple_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir) / "inbox"
            folder.mkdir()
            (folder / "2330.csv").write_text(
                "\n".join(
                    [
                        "Symbol,Date,Time,Open,High,Low,Close,TotalVolume,UpTicks,DownTicks",
                        "2330,2025/4/11,09:01:00,848,848,840,842,9801,178,176",
                    ]
                )
            )
            (folder / "MXF1.csv").write_text(
                "\n".join(
                    [
                        "Symbol,Date,Time,Open,High,Low,Close,TotalVolume,UpTicks,DownTicks",
                        "MXF1,2026/4/1,00:01:00,32276,32293,32266,32290,347,79,66",
                    ]
                )
            )
            store = SQLiteBarStore(f"{temp_dir}/bars.db")

            result = import_csv_folder(store=store, folder=folder)
            mtx_rows = store.list_bars("1m", "MTX", datetime(2026, 4, 1, 0, 1), datetime(2026, 4, 1, 0, 1))

        payload = result.to_dict()
        self.assertEqual(payload["files_seen"], 2)
        self.assertEqual(payload["upserted_bars"], 2)
        self.assertEqual({item["symbol"] for item in payload["items"]}, {"2330", "MTX"})
        self.assertEqual(len(mtx_rows), 1)
        self.assertEqual(mtx_rows[0].symbol, "MTX")
        self.assertEqual(mtx_rows[0].instrument_key, "MXF1")
        self.assertEqual(mtx_rows[0].contract_month, "202604")

    def test_import_csv_file_for_mtx_night_session_uses_trading_day_contract_month(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = f"{temp_dir}/bars.db"
            csv_path = Path(temp_dir) / "MXF1.csv"
            csv_path.write_text(
                "\n".join(
                    [
                        "Symbol,Date,Time,Open,High,Low,Close,TotalVolume,UpTicks,DownTicks",
                        "MXF1,2026/4/1,00:01:00,32276,32293,32266,32290,347,79,66",
                    ]
                )
            )
            store = SQLiteBarStore(db_path)

            result = import_csv_file(store, csv_path)
            rows = store.list_bars("1m", "MTX", datetime(2026, 4, 1, 0, 1), datetime(2026, 4, 1, 0, 1))

        self.assertEqual(result.upserted_bars, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].trading_day.isoformat(), "2026-03-31")
        self.assertEqual(rows[0].contract_month, "202604")


if __name__ == "__main__":
    unittest.main()
