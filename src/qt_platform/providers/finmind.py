from __future__ import annotations

import json
import re
import time
from datetime import date, datetime, timedelta
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from qt_platform.domain import Bar
from qt_platform.providers.base import BaseProvider
from qt_platform.session import classify_session, trading_day_for
from qt_platform.settings import FinMindSettings


class FinMindAdapter(BaseProvider):
    FUTURES_DAILY_DATASET = "TaiwanFuturesDaily"
    FUTURES_TICK_DATASET = "TaiwanFuturesTick"
    STOCK_DAILY_DATASET = "TaiwanStockPrice"
    STOCK_TICK_DATASET = "TaiwanStockPriceTick"

    def __init__(self, settings: FinMindSettings) -> None:
        self.settings = settings
        self._last_request_at = 0.0

    def supports_history(self, market: str, instrument_type: str, symbol: str, timeframe: str) -> bool:
        if instrument_type == "future" and market == "TAIFEX":
            return timeframe in {"1d", "1m"}
        if instrument_type == "stock" and market == "TWSE":
            return timeframe in {"1d", "1m"}
        return False

    def fetch_history(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        timeframe: str,
        session_scope: str,
    ) -> list[Bar]:
        if timeframe == "1d":
            if symbol.isdigit():
                return self._fetch_stock_daily(symbol, start_date, end_date)
            return self._fetch_futures_daily(symbol, start_date, end_date, session_scope)
        if timeframe == "1m":
            if symbol.isdigit():
                return self._fetch_stock_minute_from_ticks(symbol, start_date, end_date, session_scope)
            return self._fetch_minute_from_ticks(symbol, start_date, end_date, session_scope)
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    def fetch_history_batch(
        self,
        market: str,
        symbols: list[str],
        start_date: date,
        end_date: date,
        timeframe: str,
        session_scope: str,
    ) -> dict[str, list[Bar]]:
        if market == "TAIFEX" and timeframe == "1d" and all(symbol != "TXO" for symbol in symbols):
            return self._fetch_daily_batch(symbols, start_date, end_date, session_scope)
        return super().fetch_history_batch(
            market=market,
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            timeframe=timeframe,
            session_scope=session_scope,
        )

    def _fetch_futures_daily(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        session_scope: str,
    ) -> list[Bar]:
        payload = self._get(
            dataset=self.FUTURES_DAILY_DATASET,
            data_id=symbol,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )
        rows = payload.get("data", [])
        bars = [self._normalize_futures_row(row, session_scope=session_scope) for row in rows]
        bars.sort(key=lambda item: item.ts)
        return bars

    def _fetch_stock_daily(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> list[Bar]:
        payload = self._get(
            dataset=self.STOCK_DAILY_DATASET,
            data_id=symbol,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )
        rows = payload.get("data", [])
        bars = [self._normalize_stock_row(row) for row in rows]
        bars.sort(key=lambda item: item.ts)
        return bars

    def _fetch_daily_batch(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
        session_scope: str,
    ) -> dict[str, list[Bar]]:
        symbol_set = set(symbols)
        grouped: dict[str, list[Bar]] = {symbol: [] for symbol in symbols}
        day = start_date
        while day <= end_date:
            payload = self._get(
                dataset=self.FUTURES_DAILY_DATASET,
                start_date=day.isoformat(),
                end_date=day.isoformat(),
            )
            for row in payload.get("data", []):
                futures_id = str(row.get("futures_id"))
                if futures_id not in symbol_set:
                    continue
                grouped[futures_id].append(self._normalize_futures_row(row, session_scope=session_scope))
            day += timedelta(days=1)
        for bars in grouped.values():
            bars.sort(key=lambda item: item.ts)
        return grouped

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
                dataset=self.FUTURES_TICK_DATASET,
                data_id=symbol,
                start_date=day.isoformat(),
            )
            rows = payload.get("data", [])
            bars.extend(self._aggregate_ticks(rows, session_scope=session_scope))
            day += timedelta(days=1)
        bars.sort(key=lambda item: item.ts)
        return bars

    def _fetch_stock_minute_from_ticks(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        session_scope: str,
    ) -> list[Bar]:
        if session_scope == "night":
            return []
        day = start_date
        bars: list[Bar] = []
        while day <= end_date:
            payload = self._get(
                dataset=self.STOCK_TICK_DATASET,
                data_id=symbol,
                start_date=day.isoformat(),
            )
            rows = payload.get("data", [])
            bars.extend(self._aggregate_stock_ticks(rows, session_scope=session_scope))
            day += timedelta(days=1)
        bars.sort(key=lambda item: item.ts)
        return bars

    def _get(self, api_version: str = "v4", timeout_seconds: int | None = None, **params: str) -> dict:
        self._throttle()
        query = urlencode(params)
        url = f"{self._base_url(api_version)}/data?{query}"
        headers = {}
        if self.settings.token:
            headers["Authorization"] = f"Bearer {self.settings.token}"
        timeout = timeout_seconds or self.settings.timeout_seconds

        last_error: Exception | None = None
        for attempt in range(1, self.settings.retry_limit + 1):
            try:
                req = Request(url, headers=headers, method="GET")
                with urlopen(req, timeout=timeout) as resp:
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
    def _normalize_futures_row(row: dict, session_scope: str) -> Bar:
        trading_session = row.get("trading_session", "position")
        if session_scope == "day" and trading_session != "position":
            raise ValueError("Received non-day-session row while session_scope=day.")
        if session_scope == "night" and trading_session not in {"after_market", "after_hours"}:
            raise ValueError("Received non-night-session row while session_scope=night.")

        ts = datetime.fromisoformat(f"{row['date']}T00:00:00")
        return Bar(
            ts=ts,
            trading_day=datetime.fromisoformat(f"{row['date']}T00:00:00").date(),
            symbol=row["futures_id"],
            instrument_key=row["futures_id"],
            contract_month=str(row["contract_date"]),
            session=_map_session(trading_session),
            open=float(row["open"]),
            high=float(row["max"]),
            low=float(row["min"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
            open_interest=_optional_float(row.get("open_interest")),
            source="finmind",
            build_source="finmind_daily",
        )

    @staticmethod
    def _normalize_stock_row(row: dict) -> Bar:
        ts = datetime.fromisoformat(f"{row['date']}T00:00:00")
        return Bar(
            ts=ts,
            trading_day=ts.date(),
            symbol=str(row["stock_id"]),
            instrument_key=str(row["stock_id"]),
            contract_month="",
            session="day",
            open=float(row["open"]),
            high=float(row.get("max", row.get("high"))),
            low=float(row.get("min", row.get("low"))),
            close=float(row["close"]),
            volume=float(row.get("Trading_Volume", row.get("trading_volume", row.get("volume", 0)))),
            open_interest=None,
            source="finmind",
            build_source="finmind_stock_daily",
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
            symbol = str(row["futures_id"])
            contract_month = str(row["contract_date"])
            if not _include_futures_tick_contract(symbol=symbol, contract_month=contract_month):
                continue

            bucket_key = (
                ts.replace(second=0, microsecond=0),
                symbol,
                contract_month,
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
                    trading_day=trading_day_for(minute_ts),
                    symbol=symbol,
                    instrument_key=symbol,
                    contract_month=contract_month,
                    session=session,
                    open=prices[0],
                    high=max(prices),
                    low=min(prices),
                    close=prices[-1],
                    volume=sum(float(item["volume"]) for item in ordered),
                    open_interest=None,
                    source="finmind",
                    build_source="finmind_tick_agg",
                )
            )
        return bars

    @staticmethod
    def _aggregate_stock_ticks(rows: list[dict], session_scope: str) -> list[Bar]:
        if session_scope == "night":
            return []
        buckets: dict[tuple[datetime, str, str], list[dict]] = {}

        for row in rows:
            ts = datetime.fromisoformat(f"{row['date']}T{row['Time']}")
            session = classify_session(ts)
            if session != "day":
                continue
            bucket_key = (
                ts.replace(second=0, microsecond=0),
                str(row["stock_id"]),
                session,
            )
            buckets.setdefault(bucket_key, []).append(row)

        bars: list[Bar] = []
        for (minute_ts, symbol, session), bucket in sorted(buckets.items()):
            ordered = sorted(bucket, key=lambda item: str(item["Time"]))
            prices = [float(item["deal_price"]) for item in ordered]
            bars.append(
                Bar(
                    ts=minute_ts,
                    trading_day=minute_ts.date(),
                    symbol=symbol,
                    instrument_key=symbol,
                    contract_month="",
                    session=session,
                    open=prices[0],
                    high=max(prices),
                    low=min(prices),
                    close=prices[-1],
                    volume=sum(float(item["volume"]) for item in ordered),
                    open_interest=None,
                    up_ticks=sum(1 for item in ordered if item.get("TickType") == 1),
                    down_ticks=sum(1 for item in ordered if item.get("TickType") == 2),
                    source="finmind",
                    build_source="finmind_stock_tick_agg",
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


_MONTHLY_CONTRACT_PATTERN = re.compile(r"^\d{6}$")


def _include_futures_tick_contract(symbol: str, contract_month: str) -> bool:
    if symbol != "MTX":
        return True
    return bool(_MONTHLY_CONTRACT_PATTERN.fullmatch(contract_month))
