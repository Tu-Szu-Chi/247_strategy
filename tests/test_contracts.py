import unittest
from datetime import date

from qt_platform.contracts import resolve_mtx_monthly_contract, third_wednesday


class ContractsTest(unittest.TestCase):
    def test_third_wednesday(self) -> None:
        self.assertEqual(third_wednesday(2024, 1).isoformat(), "2024-01-17")

    def test_resolve_mtx_monthly_contract_before_expiry(self) -> None:
        resolved = resolve_mtx_monthly_contract(date(2024, 1, 16))
        self.assertEqual(resolved.contract_month, "202401")
        self.assertEqual(resolved.last_trading_day.isoformat(), "2024-01-17")

    def test_resolve_mtx_monthly_contract_after_expiry(self) -> None:
        resolved = resolve_mtx_monthly_contract(date(2024, 1, 18))
        self.assertEqual(resolved.contract_month, "202402")
        self.assertEqual(resolved.last_trading_day.isoformat(), "2024-02-21")


if __name__ == "__main__":
    unittest.main()
