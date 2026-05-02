from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Any, Sequence

from qt_platform.domain import Bar, CanonicalTick


@dataclass(frozen=True)
class StreamKey:
    provider: str
    symbol: str
    type: str  # e.g., "bars_1m", "ticks"
    
    def __str__(self) -> str:
        return f"{self.provider}:{self.type}:{self.symbol}"


class DataStream:
    """Represents a L1 (In-Memory) sliding window of data for a specific stream."""
    
    def __init__(self, key: StreamKey, maxlen: int = 1000):
        self.key = key
        self._data: deque[Any] = deque(maxlen=maxlen)
        self._lock = Lock()

    def append(self, item: Any):
        with self._lock:
            self._data.append(item)

    def get_history(self, n: int) -> list[Any]:
        with self._lock:
            if n <= 0:
                return []
            # Return last n items
            history = list(self._data)
            return history[-n:]

    def last(self) -> Any | None:
        with self._lock:
            return self._data[-1] if self._data else None

    @property
    def current_len(self) -> int:
        return len(self._data)


class DataManager:
    """Manages multiple DataStreams and handles cross-layer data fetching."""
    
    def __init__(self, store: Any = None):
        self.store = store  # L3 Store (e.g., BarRepository)
        self._streams: dict[str, DataStream] = {}
        self._lock = Lock()

    def get_stream(self, key: StreamKey | str) -> DataStream:
        key_str = str(key)
        with self._lock:
            if key_str not in self._streams:
                if isinstance(key, str):
                    # Basic parsing for string keys if needed, 
                    # but preferred to use StreamKey objects
                    parts = key.split(":")
                    if len(parts) >= 3:
                        key = StreamKey(provider=parts[0], type=parts[1], symbol=parts[2])
                    else:
                        raise ValueError(f"Invalid stream key format: {key}")
                
                self._streams[key_str] = DataStream(key)
            return self._streams[key_str]

    def hydrate_stream(self, key: StreamKey, start: datetime, end: datetime):
        """Fetch data from L3 (DB) and populate L1 (Memory)."""
        if not self.store:
            return
            
        # Implementation depends on store interface
        # For example, if it's bars:
        if "bars" in key.type:
            timeframe = key.type.split("_")[1] if "_" in key.type else "1m"
            bars = self.store.list_bars(
                symbol=key.symbol,
                timeframe=timeframe,
                start=start,
                end=end
            )
            stream = self.get_stream(key)
            for bar in bars:
                stream.append(bar)
        # Add logic for ticks if needed
