import unittest
from tempfile import TemporaryDirectory

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


if __name__ == "__main__":
    unittest.main()
