from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from qt_platform.contracts import root_symbol_for


@dataclass(frozen=True)
class SymbolRegistryEntry:
    symbol: str
    root_symbol: str
    market: str
    instrument_type: str
    enabled: bool = True


def load_symbol_registry(path: str | Path) -> list[SymbolRegistryEntry]:
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Symbol registry not found: {csv_path}")

    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(_iter_data_lines(handle))
        if reader.fieldnames is None:
            raise ValueError("Symbol registry CSV must include a header row.")
        required = {"symbol", "market"}
        missing = required.difference({name.strip() for name in reader.fieldnames})
        if missing:
            raise ValueError(f"Symbol registry CSV is missing required columns: {sorted(missing)}")

        entries: list[SymbolRegistryEntry] = []
        for row in reader:
            symbol = (row.get("symbol") or "").strip()
            market = (row.get("market") or "").strip()
            enabled = _parse_enabled(row.get("enabled"))
            if not symbol or not market or not enabled:
                continue
            entries.append(
                SymbolRegistryEntry(
                    symbol=symbol,
                    root_symbol=root_symbol_for(symbol),
                    market=market,
                    instrument_type=_instrument_type(row.get("instrument_type"), market, symbol),
                    enabled=True,
                )
            )
    return entries


def _iter_data_lines(handle) -> list[str]:
    return [line for line in handle if line.strip() and not line.lstrip().startswith("#")]


def _parse_enabled(raw: str | None) -> bool:
    if raw is None or raw.strip() == "":
        return True
    return raw.strip().lower() not in {"0", "false", "no", "n", "off"}


def _instrument_type(raw: str | None, market: str, symbol: str) -> str:
    if raw and raw.strip():
        return raw.strip().lower()
    if market == "TWSE":
        return "stock"
    if market == "TAIFEX":
        if root_symbol_for(symbol) in {"TX", "MTX", "TXF"}:
            return "future"
        if symbol.startswith("TX"):
            return "option"
    return "unknown"
