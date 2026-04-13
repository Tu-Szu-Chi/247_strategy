from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable

from qt_platform.domain import CanonicalTick
from qt_platform.live.base import BaseLiveProvider


class StubLiveProvider(BaseLiveProvider):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.connected = False

    def connect(self) -> None:
        self.connected = True

    def close(self) -> None:
        self.connected = False

    def stream_ticks(self, symbols: list[str], max_events: int | None = None) -> Iterable[CanonicalTick]:
        if not self.connected:
            raise RuntimeError("StubLiveProvider must be connected before streaming ticks.")
        symbol_set = set(symbols)
        count = 0
        for line in self.path.read_text().splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            if payload["symbol"] not in symbol_set:
                continue
            yield CanonicalTick(
                ts=datetime.fromisoformat(payload["ts"]),
                trading_day=datetime.fromisoformat(f"{payload['trading_day']}T00:00:00").date(),
                symbol=payload["symbol"],
                instrument_key=payload.get("instrument_key"),
                contract_month=payload.get("contract_month", ""),
                strike_price=payload.get("strike_price"),
                call_put=payload.get("call_put"),
                session=payload["session"],
                price=float(payload["price"]),
                size=float(payload["size"]),
                tick_direction=payload.get("tick_direction"),
                total_volume=payload.get("total_volume"),
                bid_side_total_vol=payload.get("bid_side_total_vol"),
                ask_side_total_vol=payload.get("ask_side_total_vol"),
                source=payload.get("source", "stub_live"),
                payload_json=json.dumps(payload, ensure_ascii=False),
            )
            count += 1
            if max_events is not None and count >= max_events:
                break
