from __future__ import annotations

import json
import io
import queue
import re
import sys
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
from datetime import date, datetime
from typing import Any, Iterable

from qt_platform.domain import CanonicalTick
from qt_platform.live.base import BaseLiveProvider, LiveUsageStatus
from qt_platform.session import classify_session, trading_day_for
from qt_platform.settings import ShioajiSettings


ROOT_SYMBOL_PATTERN = re.compile(r"^[A-Z]+")
TX_OPTION_SYMBOL_PATTERN = re.compile(r"^(TXO|TX[1-5UVXYZ])", re.IGNORECASE)
TX_OPTION_ROOT_PATTERN = re.compile(r"^TX[A-Z0-9]$")
LIVE_FUTURE_ALIAS = {
    "MTX": "MXFR1",
    "MXF": "MXFR1",
    "TX": "MXFR1",
    "TXF": "MXFR1",
}


class ShioajiLiveProvider(BaseLiveProvider):
    def __init__(
        self,
        settings: ShioajiSettings,
        idle_timeout_seconds: float = 30.0,
        simulation: bool = False,
    ) -> None:
        self.settings = settings
        self.idle_timeout_seconds = idle_timeout_seconds
        self.simulation = simulation
        self.api = None
        self._sj = None
        self._queue: queue.Queue[CanonicalTick] = queue.Queue()
        self._contracts: dict[str, Any] = {}
        self.connected = False
        self._stop_reason: str | None = None

    def connect(self) -> None:
        if not self.settings.api_key:
            raise RuntimeError("SH_API_KEY is missing.")
        if not self.settings.secret_key:
            raise RuntimeError("SH_SECRET_KEY is missing. Current loader also accepts SH_SCRET_KEY for compatibility.")

        try:
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                import shioaji as sj
        except ImportError as exc:  # pragma: no cover - depends on optional runtime dependency.
            raise RuntimeError("shioaji is not installed. Install it with: pip install shioaji") from exc

        self._sj = sj
        self.api = sj.Shioaji(simulation=self.simulation)
        self._register_callbacks()
        self.api.on_event(self._handle_event)
        self.api.login(
            api_key=self.settings.api_key,
            secret_key=self.settings.secret_key,
        )
        self.connected = True
        self._stop_reason = None

    def close(self) -> None:
        if self.api is not None:
            try:
                self.api.logout()
            except Exception:
                pass
        self.connected = False
        self.api = None
        self._sj = None
        self._contracts.clear()
        self._stop_reason = None

    def stream_ticks(self, symbols: list[str], max_events: int | None = None) -> Iterable[CanonicalTick]:
        if not self.connected or self.api is None or self._sj is None:
            raise RuntimeError("ShioajiLiveProvider must be connected before streaming ticks.")

        contracts = [self._resolve_contract(symbol) for symbol in symbols]
        return self.stream_ticks_from_contracts(contracts=contracts, max_events=max_events)

    def stream_ticks_from_contracts(self, contracts: list[Any], max_events: int | None = None) -> Iterable[CanonicalTick]:
        if not self.connected or self.api is None or self._sj is None:
            raise RuntimeError("ShioajiLiveProvider must be connected before streaming ticks.")
        for contract in contracts:
            code = getattr(contract, "code", None)
            target_code = getattr(contract, "target_code", None)
            if code:
                self._contracts[str(code)] = contract
            if target_code:
                self._contracts[str(target_code)] = contract
            self.api.quote.subscribe(
                contract,
                quote_type=self._sj.constant.QuoteType.Tick,
                version=self._sj.constant.QuoteVersion.v1,
            )

        emitted = 0
        last_usage_check = datetime.now()
        try:
            if self._should_pause_for_usage():
                self._stop_reason = "usage_threshold_reached"
                return
            while max_events is None or emitted < max_events:
                try:
                    tick = self._queue.get(timeout=self.idle_timeout_seconds)
                except queue.Empty:
                    now = datetime.now()
                    if classify_session(now) == "unknown":
                        self._stop_reason = "session_closed"
                        return
                    if (now - last_usage_check).total_seconds() >= self.settings.usage_check_interval_seconds:
                        if self._should_pause_for_usage():
                            self._stop_reason = "usage_threshold_reached"
                            return
                        last_usage_check = now
                    continue
                yield tick
                emitted += 1
                now = datetime.now()
                if (now - last_usage_check).total_seconds() >= self.settings.usage_check_interval_seconds:
                    if self._should_pause_for_usage():
                        self._stop_reason = "usage_threshold_reached"
                        return
                    last_usage_check = now
        finally:
            for contract in contracts:
                try:
                    self.api.quote.unsubscribe(
                        contract,
                        quote_type=self._sj.constant.QuoteType.Tick,
                        version=self._sj.constant.QuoteVersion.v1,
                    )
                except Exception:
                    pass

    def usage_status(self) -> LiveUsageStatus | None:
        if not self.connected or self.api is None:
            return None
        usage = self.api.usage()
        limit_bytes = int(getattr(usage, "limit_bytes", self.settings.daily_limit_bytes) or self.settings.daily_limit_bytes)
        return LiveUsageStatus(
            bytes_used=int(getattr(usage, "bytes", 0) or 0),
            limit_bytes=limit_bytes,
            remaining_bytes=int(getattr(usage, "remaining_bytes", max(limit_bytes, 0)) or 0),
            connections=int(getattr(usage, "connections", 0) or 0),
        )

    def stop_reason(self) -> str | None:
        return self._stop_reason

    def resolve_option_contracts(
        self,
        option_root: str | None = None,
        expiry_count: int = 2,
        atm_window: int = 20,
        underlying_future_symbol: str = "MXFR1",
        call_put: str = "both",
    ) -> list[Any]:
        selected_roots, contracts, _ = self.resolve_option_universe(
            option_root=option_root,
            expiry_count=expiry_count,
            atm_window=atm_window,
            underlying_future_symbol=underlying_future_symbol,
            call_put=call_put,
        )
        return contracts

    def resolve_option_universe(
        self,
        option_root: str | None = None,
        expiry_count: int = 2,
        atm_window: int = 20,
        underlying_future_symbol: str = "MXFR1",
        call_put: str = "both",
    ) -> tuple[list[str], list[Any], float]:
        if not self.connected or self.api is None:
            raise RuntimeError("ShioajiLiveProvider must be connected before resolving option contracts.")
        selected_roots = self.resolve_nearest_option_roots(
            option_root=option_root,
            root_count=expiry_count,
            now=datetime.now(),
        )
        reference_price = self._resolve_reference_price(underlying_future_symbol)
        contracts = _select_option_contracts_from_roots(
            api=self.api,
            option_roots=selected_roots,
            reference_price=reference_price,
            atm_window=atm_window,
            call_put=call_put,
        )
        if not contracts:
            raise ValueError(f"No option contracts found for roots '{selected_roots}'.")
        return selected_roots, contracts, reference_price

    def resolve_option_contract_symbols(
        self,
        option_root: str | None = None,
        expiry_count: int = 2,
        atm_window: int = 20,
        underlying_future_symbol: str = "MXFR1",
        call_put: str = "both",
    ) -> list[str]:
        selected = self.resolve_option_contracts(
            option_root=option_root,
            expiry_count=expiry_count,
            atm_window=atm_window,
            underlying_future_symbol=underlying_future_symbol,
            call_put=call_put,
        )
        return [str(contract.symbol) for contract in selected]

    def resolve_nearest_option_roots(
        self,
        option_root: str | None = None,
        root_count: int = 2,
        now: datetime | None = None,
    ) -> list[str]:
        if not self.connected or self.api is None:
            raise RuntimeError("ShioajiLiveProvider must be connected before resolving option roots.")
        current_time = now or datetime.now()
        if option_root and option_root.upper() not in {"AUTO", "TX", "TXO"}:
            return [option_root.upper()]

        candidates = []
        for root in _available_tx_option_roots(self.api):
            contracts = [contract for contract in self.api.Contracts.Options[root] if _option_delivery_date(contract) is not None]
            if not contracts:
                continue
            nearest_expiry = _nearest_expiry_dates(contracts, expiry_count=1, now=current_time)
            if not nearest_expiry:
                continue
            candidates.append((nearest_expiry[0], root))
        candidates.sort(key=lambda item: (item[0], item[1]))
        return [root for _, root in candidates[:root_count]]

    def option_root_diagnostics(self, now: datetime | None = None) -> dict[str, Any]:
        if not self.connected or self.api is None:
            raise RuntimeError("ShioajiLiveProvider must be connected before inspecting option roots.")
        current_time = now or datetime.now()
        available_roots = _available_tx_option_roots(self.api)
        roots: list[dict[str, Any]] = []
        for root in available_roots:
            contracts = list(self.api.Contracts.Options[root])
            dated_contracts = [contract for contract in contracts if _option_delivery_date(contract) is not None]
            nearest_expiry = _nearest_expiry_dates(dated_contracts, expiry_count=1, now=current_time) if dated_contracts else []
            roots.append(
                {
                    "root": root,
                    "contracts": len(contracts),
                    "dated_contracts": len(dated_contracts),
                    "nearest_expiry": nearest_expiry[0].isoformat() if nearest_expiry else None,
                }
            )
        return {
            "available_roots": available_roots,
            "roots": roots,
        }

    def _register_callbacks(self) -> None:
        assert self.api is not None

        @self.api.on_tick_stk_v1()
        def _on_stock_tick(exchange: Any, tick: Any) -> None:
            code = getattr(tick, "code", None)
            contract = self._contracts.get(code)
            ts = _tick_datetime(tick)
            symbol = str(getattr(contract, "code", None) or code or "")
            canonical = CanonicalTick(
                ts=ts,
                trading_day=trading_day_for(ts),
                symbol=symbol,
                instrument_key=symbol,
                contract_month="",
                strike_price=None,
                call_put=None,
                session=classify_session(ts),
                price=float(getattr(tick, "close", 0.0)),
                size=float(getattr(tick, "volume", 0.0)),
                tick_direction=_map_tick_direction(getattr(tick, "tick_type", None)),
                total_volume=_float_or_none(getattr(tick, "total_volume", None)),
                bid_side_total_vol=_float_or_none(getattr(tick, "bid_side_total_vol", None)),
                ask_side_total_vol=_float_or_none(getattr(tick, "ask_side_total_vol", None)),
                source="shioaji_live",
                payload_json=json.dumps(_serialize_tick_payload(exchange, tick), ensure_ascii=False, default=str),
            )
            self._queue.put(canonical)

        @self.api.on_tick_fop_v1()
        def _on_tick(exchange: Any, tick: Any) -> None:
            code = getattr(tick, "code", None)
            contract = self._contracts.get(code)
            ts = _tick_datetime(tick)
            root_symbol = _root_symbol_for_tick(code, contract)
            strike_price, call_put = _derivative_metadata(contract, code)
            canonical = CanonicalTick(
                ts=ts,
                trading_day=trading_day_for(ts),
                symbol=root_symbol,
                instrument_key=code or root_symbol,
                contract_month=_contract_month(contract),
                strike_price=strike_price,
                call_put=call_put,
                session=classify_session(ts),
                price=float(getattr(tick, "close", 0.0)),
                size=float(getattr(tick, "volume", 0.0)),
                tick_direction=_map_tick_direction(getattr(tick, "tick_type", None)),
                total_volume=_float_or_none(getattr(tick, "total_volume", None)),
                bid_side_total_vol=_float_or_none(getattr(tick, "bid_side_total_vol", None)),
                ask_side_total_vol=_float_or_none(getattr(tick, "ask_side_total_vol", None)),
                source="shioaji_live",
                payload_json=json.dumps(_serialize_tick_payload(exchange, tick), ensure_ascii=False, default=str),
            )
            self._queue.put(canonical)

    def _handle_event(self, resp_code: int, event_code: int, info: str, event_str: str) -> None:
        if resp_code in {0, 200}:
            return
        print(
            f"Response Code: {resp_code} | Event Code: {event_code} | Info: {info} | Event: {event_str}",
            file=sys.stderr,
        )

    def _resolve_contract(self, symbol: str) -> Any:
        assert self.api is not None
        contract = None
        future_symbol = LIVE_FUTURE_ALIAS.get(symbol, symbol)
        try:
            contract = self.api.Contracts.Futures[future_symbol]
        except Exception:
            pass
        if contract is None:
            contract = self._resolve_stock_contract(symbol)
        if contract is None:
            exc: Exception | None = None
            try:
                contract = self.api.Contracts.Options[symbol]
            except Exception as err:
                exc = err
            if contract is None:
                contract = self._resolve_option_contract_from_chain(symbol)
            if contract is None:
                raise ValueError(
                    f"Unable to resolve Shioaji contract for symbol '{symbol}'. "
                    "Pass the exact Shioaji contract code, for example 2330, MXFR1, or TXO20250418000C."
                ) from exc
        code = getattr(contract, "code", symbol)
        target_code = getattr(contract, "target_code", None)
        self._contracts[code] = contract
        if target_code:
            self._contracts[str(target_code)] = contract
        return contract

    def _resolve_stock_contract(self, symbol: str) -> Any | None:
        assert self.api is not None
        try:
            contract = self.api.Contracts.Stocks[symbol]
            if contract is not None:
                return contract
        except Exception:
            pass
        for market in ("TSE", "OTC", "OES"):
            try:
                bucket = getattr(self.api.Contracts.Stocks, market)
                contract = bucket[symbol]
                if contract is not None:
                    return contract
            except Exception:
                continue
        return None

    def _resolve_option_contract_from_chain(self, symbol: str) -> Any | None:
        assert self.api is not None
        root = _normalize_root_symbol(symbol)
        if root not in self.api.Contracts.Options:
            return None
        chain = self.api.Contracts.Options[root]
        try:
            contract = chain[symbol]
            if contract is not None:
                return contract
        except Exception:
            pass
        for contract in chain:
            if getattr(contract, "symbol", None) == symbol or getattr(contract, "code", None) == symbol:
                return contract
        return None

    def _resolve_reference_price(self, underlying_future_symbol: str) -> float:
        assert self.api is not None
        future_contract = self.api.Contracts.Futures[underlying_future_symbol]
        snapshots = self.api.snapshots([future_contract], timeout=5000)
        if not snapshots:
            raise RuntimeError(f"Unable to resolve snapshot for underlying future '{underlying_future_symbol}'.")
        snapshot = snapshots[0]
        price = getattr(snapshot, "close", None) or getattr(snapshot, "reference", None)
        if price in (None, 0):
            raise RuntimeError(f"Snapshot for '{underlying_future_symbol}' does not contain a usable reference price.")
        return float(price)

    def _should_pause_for_usage(self) -> bool:
        usage = self.usage_status()
        if usage is None:
            return False
        effective_limit = min(usage.limit_bytes, self.settings.daily_limit_bytes)
        if effective_limit <= 0:
            return False
        return usage.bytes_used / effective_limit >= self.settings.pause_threshold_ratio


def _tick_datetime(tick: Any) -> datetime:
    ts = getattr(tick, "datetime", None)
    if isinstance(ts, datetime):
        return ts
    raise ValueError("Shioaji tick payload does not expose a datetime field.")


def _root_symbol_for_tick(code: str | None, contract: Any) -> str:
    option_root = _option_root_symbol(code, contract)
    if option_root is not None:
        return option_root
    candidate = (
        getattr(contract, "category", None)
        or getattr(contract, "underlying_code", None)
        or getattr(contract, "symbol", None)
        or code
        or ""
    )
    return _normalize_root_symbol(str(candidate))


def _normalize_root_symbol(value: str) -> str:
    if not value:
        return value
    option_root = _extract_tx_option_root(value)
    if option_root is not None:
        return option_root
    match = ROOT_SYMBOL_PATTERN.match(value.upper())
    normalized = match.group(0) if match else value.upper()
    if normalized.startswith("MXF"):
        return "MTX"
    if normalized.startswith("TXF"):
        return "MTX"
    return normalized


def _option_root_symbol(code: str | None, contract: Any) -> str | None:
    candidates = (
        code,
        getattr(contract, "code", None),
        getattr(contract, "symbol", None),
        getattr(contract, "underlying_code", None),
        getattr(contract, "category", None),
    )
    for candidate in candidates:
        option_root = _extract_tx_option_root(candidate)
        if option_root is not None:
            return option_root
    return None


def _extract_tx_option_root(value: Any) -> str | None:
    if value in (None, ""):
        return None
    match = TX_OPTION_SYMBOL_PATTERN.match(str(value).strip().upper())
    if not match:
        return None
    return match.group(1)


def _contract_month(contract: Any) -> str:
    for attr in ("delivery_month", "delivery_date", "contract_date"):
        value = getattr(contract, attr, None)
        if value:
            return str(value)
    return ""


def _derivative_metadata(contract: Any, code: Any) -> tuple[float | None, str | None]:
    if _extract_tx_option_root(code) is None:
        return None, None
    return _strike_price(contract), _call_put(contract)


def _strike_price(contract: Any) -> float | None:
    return _float_or_none(getattr(contract, "strike_price", None))


def _call_put(contract: Any) -> str | None:
    value = getattr(contract, "option_right", None)
    if value is None:
        return None
    raw = getattr(value, "value", value)
    normalized = str(raw).strip().lower()
    if normalized in {"c", "call", "buy"}:
        return "call"
    if normalized in {"p", "put", "sell"}:
        return "put"
    return normalized


def _map_tick_direction(tick_type: Any) -> str | None:
    if tick_type is None:
        return None
    value = getattr(tick_type, "value", tick_type)
    name = getattr(tick_type, "name", str(tick_type)).lower()
    if value == 1 or "buy" in name:
        return "up"
    if value == 2 or "sell" in name:
        return "down"
    return None


def _serialize_tick_payload(exchange: Any, tick: Any) -> dict[str, Any]:
    payload = {
        "exchange": getattr(exchange, "value", str(exchange)),
        "tick": _object_to_dict(tick),
    }
    return payload


def _object_to_dict(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {k: _object_to_dict(v) for k, v in asdict(value).items()}
    if hasattr(value, "__dict__"):
        return {k: _object_to_dict(v) for k, v in vars(value).items()}
    if isinstance(value, (list, tuple)):
        return [_object_to_dict(v) for v in value]
    if isinstance(value, dict):
        return {k: _object_to_dict(v) for k, v in value.items()}
    if hasattr(value, "value"):
        return getattr(value, "value")
    return value


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _option_delivery_date(contract: Any) -> date | None:
    raw = getattr(contract, "delivery_date", None)
    if not raw:
        return None
    return datetime.strptime(str(raw), "%Y/%m/%d").date()


def _nearest_expiry_dates(contracts: list[Any], expiry_count: int, now: datetime) -> list[date]:
    unique_expiries = sorted({_option_delivery_date(contract) for contract in contracts if _option_delivery_date(contract) is not None})
    session = classify_session(now)
    today = now.date()
    if session == "day":
        pool = [expiry for expiry in unique_expiries if expiry >= today]
    else:
        pool = [expiry for expiry in unique_expiries if expiry > today]
    pool = pool or unique_expiries
    return pool[:expiry_count]


def _select_option_contracts(
    contracts: list[Any],
    expiry_dates: list[date],
    reference_price: float,
    atm_window: int,
    call_put: str,
) -> list[Any]:
    call_put = call_put.lower()
    if call_put not in {"both", "call", "put"}:
        raise ValueError("call_put must be one of: both, call, put")

    selected: list[Any] = []
    for expiry in expiry_dates:
        expiry_contracts = [contract for contract in contracts if _option_delivery_date(contract) == expiry]
        strikes = sorted({float(contract.strike_price) for contract in expiry_contracts})
        if not strikes:
            continue
        atm_index = min(range(len(strikes)), key=lambda idx: abs(strikes[idx] - reference_price))
        start_idx = max(0, atm_index - atm_window)
        end_idx = min(len(strikes), atm_index + atm_window + 1)
        selected_strikes = set(strikes[start_idx:end_idx])

        for contract in expiry_contracts:
            if float(contract.strike_price) not in selected_strikes:
                continue
            normalized_cp = _call_put(contract)
            if call_put == "call" and normalized_cp != "call":
                continue
            if call_put == "put" and normalized_cp != "put":
                continue
            selected.append(contract)

    selected.sort(
        key=lambda contract: (
            _option_delivery_date(contract) or date.max,
            float(contract.strike_price),
            _call_put(contract) or "",
        )
    )
    return selected


def _select_option_contracts_from_roots(
    api: Any,
    option_roots: list[str],
    reference_price: float,
    atm_window: int,
    call_put: str,
) -> list[Any]:
    selected: list[Any] = []
    for root in option_roots:
        contracts = [contract for contract in api.Contracts.Options[root] if _option_delivery_date(contract) is not None]
        if not contracts:
            continue
        expiry_dates = _nearest_expiry_dates(contracts, expiry_count=1, now=datetime.now())
        if not expiry_dates:
            continue
        selected.extend(
            _select_option_contracts(
                contracts=contracts,
                expiry_dates=expiry_dates,
                reference_price=reference_price,
                atm_window=atm_window,
                call_put=call_put,
            )
        )
    selected.sort(
        key=lambda contract: (
            _option_delivery_date(contract) or date.max,
            float(contract.strike_price),
            _call_put(contract) or "",
        )
    )
    return selected


def _available_tx_option_roots(api: Any) -> list[str]:
    roots = []
    for root in list(api.Contracts.Options.keys()):
        normalized = str(root).upper()
        if TX_OPTION_ROOT_PATTERN.match(normalized):
            roots.append(normalized)
    return sorted(set(roots))
