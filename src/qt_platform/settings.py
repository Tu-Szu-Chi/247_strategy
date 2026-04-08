from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only when dependency is absent.
    yaml = None


@dataclass(frozen=True)
class AppSettings:
    timezone: str = "Asia/Taipei"
    session_mode: str = "day_and_night"


@dataclass(frozen=True)
class DatabaseSettings:
    url: str


@dataclass(frozen=True)
class FinMindSettings:
    base_url: str
    token_env: str
    rps_limit: float
    retry_limit: int
    backoff_factor: float
    timeout_seconds: int

    @property
    def token(self) -> str | None:
        return os.getenv(self.token_env)


@dataclass(frozen=True)
class ReportingSettings:
    output_dir: str = "reports"


@dataclass(frozen=True)
class Settings:
    app: AppSettings
    database: DatabaseSettings
    finmind: FinMindSettings
    reporting: ReportingSettings


def load_settings(path: str | Path) -> Settings:
    path = Path(path)
    _load_dotenv(path.parent.parent / ".env")
    if yaml is None:
        raise RuntimeError("PyYAML is required to load config files.")

    raw = yaml.safe_load(path.read_text()) or {}
    return Settings(
        app=AppSettings(**_section(raw, "app")),
        database=DatabaseSettings(**_section(raw, "database")),
        finmind=FinMindSettings(**_section(raw, "finmind")),
        reporting=ReportingSettings(**_section(raw, "reporting")),
    )


def _section(raw: dict[str, Any], key: str) -> dict[str, Any]:
    return dict(raw.get(key, {}))


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())
