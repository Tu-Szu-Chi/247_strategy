from __future__ import annotations

from qt_platform.contracts import root_symbol_for
from qt_platform.symbol_registry import load_symbol_registry


def load_registry_stock_symbols(registry_path: str) -> list[str]:
    registry_entries = load_symbol_registry(registry_path)
    return sorted(
        {
            entry.symbol
            for entry in registry_entries
            if entry.instrument_type == "stock"
        }
    )


def live_symbol_for_registry_future(symbol: str) -> str:
    mapping = {
        "MTX": "MXFR1",
        "MXF": "MXFR1",
        "TX": "MXFR1",
        "TXF": "MXFR1",
    }
    return mapping.get(symbol, mapping.get(root_symbol_for(symbol), symbol))
