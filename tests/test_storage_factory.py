import unittest

from qt_platform.storage.bar_store import SQLiteBarStore
from qt_platform.storage.factory import build_bar_repository


class StorageFactoryTest(unittest.TestCase):
    def test_build_sqlite_repository(self) -> None:
        repo = build_bar_repository("sqlite:///tmp/test-storage.db")
        self.assertIsInstance(repo, SQLiteBarStore)


if __name__ == "__main__":
    unittest.main()
