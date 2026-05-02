from __future__ import annotations

from typing import Type
from qt_platform.indicators.base import Indicator


class IndicatorRegistry:
    _registry: dict[str, Type[Indicator]] = {}

    @classmethod
    def register(cls, indicator_cls: Type[Indicator]):
        cls._registry[_resolve_indicator_name(indicator_cls)] = indicator_cls
        return indicator_cls

    @classmethod
    def get(cls, name: str) -> Type[Indicator] | None:
        return cls._registry.get(name)

    @classmethod
    def list_all(cls) -> list[str]:
        return list(cls._registry.keys())


def register_indicator(cls: Type[Indicator]):
    return IndicatorRegistry.register(cls)


def _resolve_indicator_name(indicator_cls: Type[Indicator]) -> str:
    try:
        instance = indicator_cls()
    except TypeError as exc:  # pragma: no cover - defensive failure for future indicators
        raise TypeError(
            f"Indicator '{indicator_cls.__name__}' must be default-constructible to use @register_indicator."
        ) from exc
    name = getattr(instance, "name", None)
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"Indicator '{indicator_cls.__name__}' produced an invalid registry name: {name!r}")
    return name
