from __future__ import annotations

from datetime import timedelta
from qt_platform.indicators.base import Indicator, IndicatorValue, StreamType
from qt_platform.indicators.registry import register_indicator


@register_indicator
class TrendQualityIndicator(Indicator):
    """
    Calculates Trend Quality Score based on ADX and Choppiness.
    Formula: ((adx_14 * 1.4 + (100 - choppiness_14)) / 2.4)
    """
    
    @property
    def name(self) -> str:
        return "trend_quality_score"

    @property
    def dependencies(self) -> list[str]:
        return ["regime"]

    def update(self, context) -> IndicatorValue:
        regime = context.get_dependency("regime")
        if not regime:
            return IndicatorValue(value=0.0, timestamp=context.ts)
            
        adx = float(regime.get("adx_14", 0.0) or 0.0)
        chop = float(regime.get("choppiness_14", 0.0) or 0.0)
        
        score = (adx * 1.4 + (100.0 - chop)) / 2.4
        score = max(0.0, min(100.0, score))
        
        return IndicatorValue(value=round(score, 2), timestamp=context.ts)


@register_indicator
class StructureStateIndicator(Indicator):
    """
    Identifies the market structure state (Trend vs Range) 
    using directional drive and expansion ratio.
    """
    
    def __init__(self) -> None:
        self._drive_history = [] # list of (ts, value)
        self._expansion_history = []
        self._sticky_state = 0

    @property
    def name(self) -> str:
        return "structure_state"

    @property
    def dependencies(self) -> list[str]:
        return ["regime"]

    def update(self, context) -> IndicatorValue:
        regime = context.get_dependency("regime")
        if not regime:
            return IndicatorValue(value=0, timestamp=context.ts)
            
        # Extract inputs from regime
        eff = float(regime.get("directional_efficiency_15b", 0.0) or 0.0)
        imb = float(regime.get("tick_imbalance_5b", 0.0) or 0.0)
        exp = float(regime.get("range_ratio_5b_30b", 0.0) or 0.0)
        
        drive = eff * imb
        self._drive_history.append((context.ts, drive))
        self._expansion_history.append((context.ts, exp))
        
        # Keep 30m window
        cutoff = context.ts - timedelta(minutes=30)
        self._drive_history = [p for p in self._drive_history if p[0] >= cutoff]
        self._expansion_history = [p for p in self._expansion_history if p[0] >= cutoff]
        
        # Calculate thresholds
        if len(self._drive_history) < 5:
            return IndicatorValue(value=0, timestamp=context.ts)
            
        from qt_platform.monitor.indicator_backend import rolling_quantile
        
        drive_vals = [abs(p[1]) for p in self._drive_history]
        exp_vals = [p[1] for p in self._expansion_history]
        
        drive_threshold = max(rolling_quantile(drive_vals, 0.65), 0.08)
        exp_threshold = max(rolling_quantile(exp_vals, 0.60), 0.12)
        
        current_drive = drive
        current_exp = exp
        
        new_state = 0
        if current_exp > exp_threshold:
            if current_drive > drive_threshold:
                new_state = 1
            elif current_drive < -drive_threshold:
                new_state = -1
        
        if new_state != 0:
            self._sticky_state = new_state
            
        return IndicatorValue(value=self._sticky_state, timestamp=context.ts)
