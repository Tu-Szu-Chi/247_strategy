from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from qt_platform.indicators.base import IndicatorValue
from qt_platform.indicators.data import DataStream


class IndicatorContext:
    """
    Provides the environment for an indicator to perform its calculation.
    Maps logical slots to physical data streams and provides access to dependencies.
    """
    
    def __init__(
        self,
        *,
        ts: datetime,
        input_mapping: Mapping[str, DataStream],
        dependency_results: Mapping[str, IndicatorValue],
        metadata: Mapping[str, Any] | None = None,
    ):
        self.ts = ts
        self._input_mapping = input_mapping
        self._dependency_results = dependency_results
        self.metadata = metadata or {}

    def get_input(self, slot_name: str) -> Any | list[Any]:
        """Get the latest item(s) from the stream(s) mapped to this slot."""
        mapped = self._input_mapping.get(slot_name)
        if mapped is None:
            return None
            
        if isinstance(mapped, (list, tuple)):
            return [stream.last() for stream in mapped]
        return mapped.last()

    def get_history(self, slot_name: str, n: int) -> list[Any] | list[list[Any]]:
        """Get the last n items from the stream(s) mapped to this slot."""
        mapped = self._input_mapping.get(slot_name)
        if mapped is None:
            return []
            
        if isinstance(mapped, (list, tuple)):
            return [stream.get_history(n) for stream in mapped]
        return mapped.get_history(n)

    def get_dependency(self, indicator_name: str) -> Any:
        """Get the current value of a dependency indicator."""
        result = self._dependency_results.get(indicator_name)
        if result is None:
            return None
        return result.value

    def get_dependency_full(self, indicator_name: str) -> IndicatorValue | None:
        """Get the full IndicatorValue of a dependency indicator."""
        return self._dependency_results.get(indicator_name)
