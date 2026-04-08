from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from qt_platform.domain import Bar
from qt_platform.providers.base import BaseProvider
from qt_platform.session import classify_session
from qt_platform.settings import FinMindSettings


class FinMindAdapter(BaseProvider):
    DAILY_DATASET = "TaiwanFuturesDaily"
    TICK_DATASET = "TaiwanFuturesTick"

    def __init__(self, settings: FinMindSettings) -> None:
        self.settings = settings
        self._last_request_at = 0.0

    def fetch_history(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        timeframe: str,
        session_scope: str,
    ) -> list[Bar]:
        if timeframe == "1d":
            return self._fetch_daily(symbol, start_date, end_date, session_scope)
        if timeframe == "1m":
            return self._fetch_minute_from_ticks(symbol, start_date, end_date, session_scope)
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    def _fetch_daily(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        session_scope: str,
    ) -> list[Bar]:
        payload = self._get(
            dataset=self.DAILY_DATASET,
            data_id=symbol,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )
        rows = payload.get("data", [])
        bars = [self._normalize_row(row, session_scope=session_scope) for row in rows]
        bars.sort(key=lambda item: item.ts)
        return bars

    def _fetch_minute_from_ticks(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        session_scope: str,
    ) -> list[Bar]:
        day = start_date
        bars: list[Bar] = []
        while day <= end_date:
            payload = self._get(
                dataset=self.TICK_DATASET,
                data_id=symbol,
                start_date=day.isoformat(),
            )
            rows = payload.get("data", [])
            bars.extend(self._aggregate_ticks(rows, session_scope=session_scope))
            day += timedelta(days=1)
        bars.sort(key=lambda item: item.ts)
        return bars

    def _get(self, api_version: str = "v4", **params: str) -> dict:
        self._throttle()
        query = urlencode(params)
        url = f"{self._base_url(api_version)}/data?{query}"
        headers = {}
        if self.settings.token:
            headers["Authorization"] = f"Bearer {self.settings.token}"

        last_error: Exception | None = None
        for attempt in range(1, self.settings.retry_limit + 1):
            try:
                req = Request(url, headers=headers, method="GET")
                with urlopen(req, timeout=self.settings.timeout_seconds) as resp:
                    self._last_request_at = time.monotonic()
                    return json.loads(resp.read().decode("utf-8"))
            except Exception as exc:  # pragma: no cover - network failure path.
                error_body = ""
                if hasattr(exc, "read"):
                    try:
                        error_body = exc.read().decode("utf-8", errors="ignore")
                    except Exception:
                        error_body = ""
                if getattr(exc, "code", None):
                    last_error = RuntimeError(
                        f"FinMind request failed with HTTP {exc.code} for {url}: {error_body}"
                    )
                else:
                    last_error = exc
                if attempt >= self.settings.retry_limit:
                    break
                delay = self.settings.backoff_factor ** (attempt - 1)
                time.sleep(delay)
        raise RuntimeError(f"FinMind request failed: {last_error}") from last_error

    def _base_url(self, api_version: str) -> str:
        marker = "/api/"
        if marker not in self.settings.base_url:
            return self.settings.base_url.rstrip("/")
        prefix = self.settings.base_url.split(marker, 1)[0]
        return f"{prefix}{marker}{api_version}"

    def _throttle(self) -> None:
        min_interval = 1 / self.settings.rps_limit if self.settings.rps_limit > 0 else 0
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)

    @staticmethod
    def _normalize_row(row: dict, session_scope: str) -> Bar:
        trading_session = row.get("trading_session", "position")
        if session_scope == "day" and trading_session != "position":
            raise ValueError("Received non-day-session row while session_scope=day.")
        if session_scope == "night" and trading_session not in {"after_market", "after_hours"}:
            raise ValueError("Received non-night-session row while session_scope=night.")

        ts = datetime.fromisoformat(f"{row['date']}T00:00:00")
        return Bar(
            ts=ts,
            symbol=row["futures_id"],
            contract_month=str(row["contract_date"]),
            session=_map_session(trading_session),
            open=float(row["open"]),
            high=float(row["max"]),
            low=float(row["min"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
            open_interest=_optional_float(row.get("open_interest")),
            source="finmind",
        )

    @staticmethod
    def _aggregate_ticks(rows: list[dict], session_scope: str) -> list[Bar]:
        buckets: dict[tuple[datetime, str, str, str], list[dict]] = {}

        for row in rows:
            ts = datetime.fromisoformat(str(row["date"]))
            session = classify_session(ts)
            if session_scope == "day" and session != "day":
                continue
            if session_scope == "night" and session != "night":
                continue
            if session == "unknown":
                continue

            bucket_key = (
                ts.replace(second=0, microsecond=0),
                str(row["futures_id"]),
                str(row["contract_date"]),
                session,
            )
            buckets.setdefault(bucket_key, []).append(row)

        bars: list[Bar] = []
        for (minute_ts, symbol, contract_month, session), bucket in sorted(buckets.items()):
            ordered = sorted(bucket, key=lambda item: str(item["date"]))
            prices = [float(item["price"]) for item in ordered]
            bars.append(
                Bar(
                    ts=minute_ts,
                    symbol=symbol,
                    contract_month=contract_month,
                    session=session,
                    open=prices[0],
                    high=max(prices),
                    low=min(prices),
                    close=prices[-1],
                    volume=sum(float(item["volume"]) for item in ordered),
                    open_interest=None,
                    source="finmind",
                )
            )
        return bars


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _map_session(trading_session: str) -> str:
    mapping = {
        "position": "day",
        "after_market": "night",
        "after_hours": "night",
    }
    return mapping.get(trading_session, trading_session)
