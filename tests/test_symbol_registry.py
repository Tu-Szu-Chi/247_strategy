import unittest
from tempfile import TemporaryDirectory

from qt_platform.live.universe import load_registry_stock_symbols
from qt_platform.symbol_registry import load_symbol_registry


class SymbolRegistryTest(unittest.TestCase):
    def test_load_symbol_registry_skips_disabled_and_comments(self) -> None:
        with TemporaryDirectory() as temp_dir:
            csv_path = f"{temp_dir}/symbols.csv"
            with open(csv_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "# registry\n"
                    "symbol,market,enabled\n"
                    "MTX,TAIFEX,true\n"
                    "MXF,TAIFEX,false\n"
                    "MTX_MAIN,TAIFEX,\n"
                )

            entries = load_symbol_registry(csv_path)

        self.assertEqual([entry.symbol for entry in entries], ["MTX", "MTX_MAIN"])
        self.assertEqual(entries[1].root_symbol, "MTX")
        self.assertEqual(entries[0].instrument_type, "future")

    def test_load_registry_stock_symbols_returns_enabled_stocks_only(self) -> None:
        with TemporaryDirectory() as temp_dir:
            csv_path = f"{temp_dir}/symbols.csv"
            with open(csv_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "symbol,market,instrument_type,enabled\n"
                    "2330,TWSE,stock,true\n"
                    "2317,TWSE,stock,\n"
                    "MXF,TAIFEX,future,true\n"
                    "2603,TWSE,stock,false\n"
                )

            symbols = load_registry_stock_symbols(csv_path)

        self.assertEqual(symbols, ["2317", "2330"])


if __name__ == "__main__":
    unittest.main()
