from __future__ import annotations

from abc import abstractmethod
from qt_platform.indicators.base import Indicator, IndicatorValue, StreamType
from qt_platform.indicators.registry import register_indicator


class RegimeProxyIndicator(Indicator):
    """Base for indicators that extract values from the main 'regime' indicator."""
    
    @property
    def dependencies(self) -> list[str]:
        return ["regime"]

    def update(self, context) -> IndicatorValue:
        regime = context.get_dependency("regime")
        if not regime:
            return IndicatorValue(value=0.0, timestamp=context.ts)
        
        val = regime.get(self.regime_field, 0.0)
        return IndicatorValue(value=val, timestamp=context.ts)

    @property
    @abstractmethod
    def regime_field(self) -> str:
        pass


@register_indicator
class ChopScoreIndicator(RegimeProxyIndicator):
    @property
    def name(self) -> str:
        return "chop_score"
    
    @property
    def regime_field(self) -> str:
        return "chop_score"


@register_indicator
class TrendScoreIndicator(RegimeProxyIndicator):
    @property
    def name(self) -> str:
        return "trend_score"
    
    @property
    def regime_field(self) -> str:
        return "trend_score"


@register_indicator
class ReversalRiskIndicator(RegimeProxyIndicator):
    @property
    def name(self) -> str:
        return "reversal_risk"
    
    @property
    def regime_field(self) -> str:
        return "reversal_risk"


@register_indicator
class VwapDistanceIndicator(RegimeProxyIndicator):
    @property
    def name(self) -> str:
        return "vwap_distance_bps"
    
    @property
    def regime_field(self) -> str:
        return "vwap_distance_bps"


@register_indicator
class ExpansionScoreIndicator(RegimeProxyIndicator):
    @property
    def name(self) -> str:
        return "expansion_score"
    
    @property
    def regime_field(self) -> str:
        return "expansion_score"


@register_indicator
class CompressionScoreIndicator(RegimeProxyIndicator):
    @property
    def name(self) -> str:
        return "compression_score"
    
    @property
    def regime_field(self) -> str:
        return "compression_score"


@register_indicator
class AdxIndicator(RegimeProxyIndicator):
    @property
    def name(self) -> str:
        return "adx_14"
    
    @property
    def regime_field(self) -> str:
        return "adx_14"


@register_indicator
class ChoppinessIndicator(RegimeProxyIndicator):
    @property
    def name(self) -> str:
        return "choppiness_14"
    
    @property
    def regime_field(self) -> str:
        return "choppiness_14"


@register_indicator
class SessionCvdIndicator(RegimeProxyIndicator):
    @property
    def name(self) -> str:
        return "session_cvd"
    
    @property
    def regime_field(self) -> str:
        return "session_cvd"
