from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from qt_platform.contracts import resolve_mtx_monthly_contract
from qt_platform.domain import Bar
from qt_platform.session import classify_session, trading_day_for
from qt_platform.storage.base import BarRepository


REQUIRED_COLUMNS = {
    "Symbol",
    "Date",
    "Time",
    "Open",
    "High",
    "Low",
    "Close",
    "TotalVolume",
}


@dataclass(frozen=True)
class CsvImportFileResult:
    path: str
    symbol: str
    rows_read: int
    upserted_bars: int
    first_ts: str | None
    last_ts: str | None
    timeframe: str = "1m"


@dataclass(frozen=True)
class CsvImportResult:
    folder: str
    files_seen: int
    files_imported: int
    rows_read: int
    upserted_bars: int
    items: list[CsvImportFileResult]

    def to_dict(self) -> dict:
        return asdict(self)


def import_csv_folder(
    store: BarRepository,
    folder: str | Path,
    pattern: str = "*.csv",
    source: str = "broker_csv",
    build_source: str = "csv_1m_import",
    chunk_size: int = 5000,
) -> CsvImportResult:
    base = Path(folder)
    files = sorted(path for path in base.rglob(pattern) if path.is_file())
    results: list[CsvImportFileResult] = []

    for path in files:
        result = import_csv_file(
            store=store,
            path=path,
            source=source,
            build_source=build_source,
            chunk_size=chunk_size,
        )
        results.append(result)

    return CsvImportResult(
        folder=str(base),
        files_seen=len(files),
        files_imported=len(results),
        rows_read=sum(item.rows_read for item in results),
        upserted_bars=sum(item.upserted_bars for item in results),
        items=results,
    )


def import_csv_file(
    store: BarRepository,
    path: str | Path,
    source: str = "broker_csv",
    build_source: str = "csv_1m_import",
    chunk_size: int = 5000,
) -> CsvImportFileResult:
    csv_path = Path(path)
    rows_read = 0
    upserted = 0
    first_ts: str | None = None
    last_ts: str | None = None
    symbol: str | None = None
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"{csv_path} has no header row.")
        missing = REQUIRED_COLUMNS.difference(reader.fieldnames)
        if missing:
            raise ValueError(f"{csv_path} is missing required columns: {sorted(missing)}")
        batch: list[Bar] = []
        for row in reader:
            bar = _row_to_bar(row, source=source, build_source=build_source)
            batch.append(bar)
            rows_read += 1
            symbol = symbol or bar.symbol
            first_ts = first_ts or bar.ts.isoformat()
            last_ts = bar.ts.isoformat()
            if len(batch) >= chunk_size:
                upserted += store.upsert_bars("1m", batch)
                batch.clear()
        if batch:
            upserted += store.upsert_bars("1m", batch)

    symbol = symbol or csv_path.stem
    return CsvImportFileResult(
        path=str(csv_path),
        symbol=symbol,
        rows_read=rows_read,
        upserted_bars=upserted,
        first_ts=first_ts,
        last_ts=last_ts,
    )


def _row_to_bar(row: dict[str, str], source: str, build_source: str) -> Bar:
    raw_symbol = row["Symbol"].strip()
    symbol = _canonical_symbol_for(raw_symbol)
    ts = _parse_timestamp(row["Date"], row["Time"])
    trading_day = trading_day_for(ts)
    session = classify_session(ts)
    return Bar(
        ts=ts,
        trading_day=trading_day,
        symbol=symbol,
        instrument_key=_instrument_key_for(raw_symbol),
        contract_month=_contract_month_for(raw_symbol, trading_day),
        session=session,
        open=float(row["Open"]),
        high=float(row["High"]),
        low=float(row["Low"]),
        close=float(row["Close"]),
        volume=float(row["TotalVolume"]),
        open_interest=None,
        up_ticks=_optional_float(row.get("UpTicks")),
        down_ticks=_optional_float(row.get("DownTicks")),
        source=source,
        build_source=build_source,
    )


def _parse_timestamp(raw_date: str, raw_time: str) -> datetime:
    return datetime.strptime(f"{raw_date.strip()} {raw_time.strip()}", "%Y/%m/%d %H:%M:%S")


def _instrument_key_for(symbol: str) -> str:
    if symbol == "TWOTC":
        return "index:TWOTC"
    return symbol


def _contract_month_for(symbol: str, trading_day: date) -> str:
    if symbol == "TWOTC" or symbol.isdigit():
        return ""
    if _canonical_symbol_for(symbol) == "MTX":
        return resolve_mtx_monthly_contract(trading_day).contract_month
    return symbol


def _canonical_symbol_for(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if normalized.startswith("MXF"):
        return "MTX"
    return normalized


def _optional_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    return float(stripped)
