from __future__ import annotations

from pathlib import Path

from qt_platform.storage.bar_store import SQLiteBarStore
from qt_platform.storage.base import BarRepository
from qt_platform.storage.postgres_store import PostgresBarStore


def build_bar_repository(database_url: str) -> BarRepository:
    sqlite_prefix = "sqlite:///"
    postgres_prefixes = ("postgresql://", "postgres://")

    if database_url.startswith(sqlite_prefix):
        return SQLiteBarStore(Path(database_url.removeprefix(sqlite_prefix)))
    if database_url.startswith(postgres_prefixes):
        return PostgresBarStore(database_url)
    raise ValueError("Unsupported database URL. Use sqlite:/// or postgresql://")

