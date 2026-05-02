from __future__ import annotations

from qt_platform.indicators.base import Indicator, IndicatorValue, StreamType
from qt_platform.indicators.registry import register_indicator
from qt_platform.indicators.collection.pressure_logic import compute_pressure_metrics


@register_indicator
class PressureIndicator(Indicator):
    """
    Calculates Option Pressure Metrics.
    Expects a list of option contracts and an underlying price.
    """
    
    @property
    def name(self) -> str:
        return "option_pressure"

    @property
    def input_slots(self) -> dict[str, StreamType]:
        return {
            "options": StreamType.TICK,  # List of option streams
            "underlying": StreamType.PRICE_ONLY  # Single underlying price stream
        }

    def update(self, context) -> IndicatorValue:
        option_bars = context.get_input("options")
        underlying_bar = context.get_input("underlying")
        
        if not option_bars or underlying_bar is None:
            return IndicatorValue(
                value={
                    "raw_pressure": 0,
                    "pressure_index": 0,
                    "raw_pressure_weighted": 0,
                    "pressure_index_weighted": 0,
                },
                timestamp=context.ts
            )
            
        underlying_price = getattr(underlying_bar, "close", None)
        
        contracts = []
        for bar in option_bars:
            if bar is None:
                continue
            contracts.append({
                "contract_month": getattr(bar, "contract_month", ""),
                "strike_price": getattr(bar, "strike_price", 0.0),
                "call_put": getattr(bar, "call_put", ""),
                "cumulative_buy_volume": getattr(bar, "cumulative_buy_volume", 0.0) or getattr(bar, "buy_volume", 0.0),
                "cumulative_sell_volume": getattr(bar, "cumulative_sell_volume", 0.0) or getattr(bar, "sell_volume", 0.0),
            })
            
        metrics = compute_pressure_metrics(
            contracts=contracts,
            underlying_reference_price=underlying_price
        )
        
        return IndicatorValue(
            value=metrics,
            timestamp=context.ts,
            metadata={"contract_count": len(contracts)}
        )
