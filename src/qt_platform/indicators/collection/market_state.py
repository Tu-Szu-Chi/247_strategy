from __future__ import annotations

from qt_platform.indicators.base import Indicator, IndicatorValue, StreamType
from qt_platform.indicators.registry import register_indicator
from qt_platform.market_state.mtx import MtxRegimeAnalyzer


@register_indicator
class RegimeIndicator(Indicator):
    """
    Wraps MtxRegimeAnalyzer to provide regime features as an indicator.
    """
    
    def __init__(self) -> None:
        self._analyzer = MtxRegimeAnalyzer()
        self._last_processed_ts = None

    @property
    def name(self) -> str:
        return "regime"

    @property
    def input_slots(self) -> dict[str, StreamType]:
        return {
            "bar": StreamType.BAR,
            "tick": StreamType.TICK
        }

    def update(self, context) -> IndicatorValue:
        bar = context.get_input("bar")
        tick = context.get_input("tick")
        
        # MtxRegimeAnalyzer handles incremental updates.
        # Note: In a pure stateless model, we would pass the full history.
        # Here we leverage the analyzer's internal state for efficiency.
        if bar and (self._last_processed_ts is None or bar.ts > self._last_processed_ts):
            self._analyzer.ingest_bar(bar)
            self._last_processed_ts = bar.ts
            
        if tick and (self._last_processed_ts is None or tick.ts > self._last_processed_ts):
            self._analyzer.ingest_tick(tick)
            self._last_processed_ts = tick.ts

        snapshot = self._analyzer.snapshot(context.ts)
        
        return IndicatorValue(
            value=snapshot.to_dict(),
            timestamp=context.ts
        )
