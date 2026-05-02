from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MonitorIndicatorSpec:
    name: str
    category: str
    requires_market_state: bool = False
    stateful_series: bool = False


MONITOR_INDICATOR_SPECS: tuple[MonitorIndicatorSpec, ...] = (
    MonitorIndicatorSpec("pressure_index", "option_flow"),
    MonitorIndicatorSpec("raw_pressure", "option_flow"),
    MonitorIndicatorSpec("pressure_index_weighted", "option_flow"),
    MonitorIndicatorSpec("raw_pressure_weighted", "option_flow"),
    MonitorIndicatorSpec("regime_state", "market_state", requires_market_state=True, stateful_series=True),
    MonitorIndicatorSpec("structure_state", "market_state", requires_market_state=True, stateful_series=True),
    MonitorIndicatorSpec("trend_score", "market_state", requires_market_state=True),
    MonitorIndicatorSpec("chop_score", "market_state", requires_market_state=True),
    MonitorIndicatorSpec("reversal_risk", "market_state", requires_market_state=True),
    MonitorIndicatorSpec("vwap_distance_bps", "market_state", requires_market_state=True),
    MonitorIndicatorSpec("directional_efficiency_15b", "market_state", requires_market_state=True),
    MonitorIndicatorSpec("tick_imbalance_5b", "market_state", requires_market_state=True),
    MonitorIndicatorSpec("trade_intensity_ratio_30b", "market_state", requires_market_state=True),
    MonitorIndicatorSpec("range_ratio_5b_30b", "market_state", requires_market_state=True),
    MonitorIndicatorSpec("adx_14", "market_state", requires_market_state=True),
    MonitorIndicatorSpec("plus_di_14", "market_state", requires_market_state=True),
    MonitorIndicatorSpec("minus_di_14", "market_state", requires_market_state=True),
    MonitorIndicatorSpec("di_bias_14", "market_state", requires_market_state=True),
    MonitorIndicatorSpec("choppiness_14", "market_state", requires_market_state=True),
    MonitorIndicatorSpec("compression_score", "market_state", requires_market_state=True),
    MonitorIndicatorSpec("expansion_score", "market_state", requires_market_state=True),
    MonitorIndicatorSpec(
        "compression_expansion_state",
        "market_state",
        requires_market_state=True,
        stateful_series=True,
    ),
    MonitorIndicatorSpec("session_cvd", "market_state", requires_market_state=True),
    MonitorIndicatorSpec("cvd_5b_delta", "market_state", requires_market_state=True),
    MonitorIndicatorSpec("cvd_15b_delta", "market_state", requires_market_state=True),
    MonitorIndicatorSpec("cvd_5b_slope", "market_state", requires_market_state=True),
    MonitorIndicatorSpec("cvd_price_alignment", "market_state", requires_market_state=True, stateful_series=True),
    MonitorIndicatorSpec("price_cvd_divergence_15b", "market_state", requires_market_state=True, stateful_series=True),
    MonitorIndicatorSpec("iv_skew", "option_iv"),
    MonitorIndicatorSpec("trend_quality_score", "derived", requires_market_state=True),
    MonitorIndicatorSpec("trend_bias_state", "derived", requires_market_state=True, stateful_series=True),
    MonitorIndicatorSpec("flow_impulse_score", "derived", requires_market_state=True),
    MonitorIndicatorSpec("flow_state", "derived", requires_market_state=True, stateful_series=True),
    MonitorIndicatorSpec("range_state", "derived", requires_market_state=True, stateful_series=True),
)

MONITOR_INDICATOR_SERIES_NAMES: tuple[str, ...] = tuple(spec.name for spec in MONITOR_INDICATOR_SPECS)
STATEFUL_MONITOR_SERIES_NAMES: frozenset[str] = frozenset(
    spec.name for spec in MONITOR_INDICATOR_SPECS if spec.stateful_series
)
MARKET_STATE_SERIES_NAMES: frozenset[str] = frozenset(
    spec.name for spec in MONITOR_INDICATOR_SPECS if spec.requires_market_state
)


def requires_market_state(names: list[str] | tuple[str, ...] | set[str]) -> bool:
    return any(name in MARKET_STATE_SERIES_NAMES for name in names)
