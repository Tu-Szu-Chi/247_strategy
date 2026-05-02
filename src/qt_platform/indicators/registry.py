from __future__ import annotations

from typing import Type
from qt_platform.indicators.base import Indicator


class IndicatorRegistry:
    _registry: dict[str, Type[Indicator]] = {}

    @classmethod
    def register(cls, indicator_cls: Type[Indicator]):
        cls._registry[indicator_cls.name] = indicator_cls
        return indicator_cls

    @classmethod
    def get(cls, name: str) -> Type[Indicator] | None:
        return cls._registry.get(name)

    @classmethod
    def list_all(cls) -> list[str]:
        return list(cls._registry.keys())


def register_indicator(cls: Type[Indicator]):
    return IndicatorRegistry.register(cls)
