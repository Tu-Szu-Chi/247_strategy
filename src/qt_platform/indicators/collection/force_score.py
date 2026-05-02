from __future__ import annotations

from qt_platform.indicators.base import Indicator, IndicatorValue, StreamType
from qt_platform.indicators.registry import register_indicator


@register_indicator
class ForceScoreIndicator(Indicator):
    """
    Calculates the Force Score based on tick bias and volume.
    Logic: (net_tick_count / tick_total) * volume
    """
    
    @property
    def name(self) -> str:
        return "force_score"

    @property
    def input_slots(self) -> dict[str, StreamType]:
        return {"src": StreamType.BAR}

    def update(self, context) -> IndicatorValue:
        bar = context.get_input("src")
        if bar is None:
            return IndicatorValue(value=0.0, timestamp=context.ts)
            
        up_ticks = getattr(bar, "up_ticks", 0.0) or 0.0
        down_ticks = getattr(bar, "down_ticks", 0.0) or 0.0
        volume = getattr(bar, "volume", 0.0) or 0.0
        
        tick_total = up_ticks + down_ticks
        net_tick_count = up_ticks - down_ticks
        
        tick_bias_ratio = net_tick_count / tick_total if tick_total > 0 else 0.0
        force_score = tick_bias_ratio * volume if tick_total > 0 else 0.0
        
        return IndicatorValue(
            value=force_score,
            timestamp=context.ts,
            metadata={
                "tick_bias_ratio": tick_bias_ratio,
                "volume": volume,
                "tick_total": tick_total
            }
        )
