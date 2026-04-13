from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Iterable

from qt_platform.domain import CanonicalTick


@dataclass(frozen=True)
class LiveUsageStatus:
    bytes_used: int
    limit_bytes: int
    remaining_bytes: int
    connections: int | None = None

    @property
    def usage_ratio(self) -> float:
        if self.limit_bytes <= 0:
            return 0.0
        return self.bytes_used / self.limit_bytes

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["usage_ratio"] = self.usage_ratio
        return payload


class BaseLiveProvider(ABC):
    @abstractmethod
    def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def stream_ticks(self, symbols: list[str], max_events: int | None = None) -> Iterable[CanonicalTick]:
        raise NotImplementedError

    def usage_status(self) -> LiveUsageStatus | None:
        return None

    def stop_reason(self) -> str | None:
        return None
