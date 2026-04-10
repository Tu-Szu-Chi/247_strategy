import unittest
from datetime import date, datetime

from qt_platform.contracts import root_symbol_for, select_symbol_view
from qt_platform.domain import Bar


class ContractSymbolViewTest(unittest.TestCase):
    def test_root_symbol_for_mtx_main(self) -> None:
        self.assertEqual(root_symbol_for("MTX_MAIN"), "MTX")

    def test_select_symbol_view_filters_to_current_main_contract(self) -> None:
        bars = [
            Bar(datetime(2024, 1, 16, 8, 45), date(2024, 1, 16), "MTX", "202401", "day", 1, 1, 1, 1, 1, None, "test"),
            Bar(datetime(2024, 1, 16, 8, 45), date(2024, 1, 16), "MTX", "202402", "day", 2, 2, 2, 2, 2, None, "test"),
            Bar(datetime(2024, 1, 18, 8, 45), date(2024, 1, 18), "MTX", "202401", "day", 3, 3, 3, 3, 3, None, "test"),
            Bar(datetime(2024, 1, 18, 8, 45), date(2024, 1, 18), "MTX", "202402", "day", 4, 4, 4, 4, 4, None, "test"),
        ]

        selected = select_symbol_view("MTX_MAIN", bars)

        self.assertEqual(len(selected), 2)
        self.assertEqual(selected[0].contract_month, "202401")
        self.assertEqual(selected[1].contract_month, "202402")
