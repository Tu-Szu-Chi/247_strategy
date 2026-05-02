from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock
from typing import Any, Mapping

from qt_platform.indicators.base import Indicator, IndicatorValue
from qt_platform.indicators.context import IndicatorContext
from qt_platform.indicators.data import DataManager, DataStream


@dataclass
class IndicatorInstance:
    indicator: Indicator
    input_mapping: Mapping[str, DataStream]
    last_result: IndicatorValue | None = None


class Pipeline:
    """A collection of indicator instances with a specific execution order (DAG)."""
    
    def __init__(self, name: str, instances: dict[str, IndicatorInstance]):
        self.name = name
        self.instances = instances
        self.execution_order = self._resolve_dag()
        self.last_accessed_at = datetime.now()

    def _resolve_dag(self) -> list[str]:
        """Simple topological sort to resolve dependencies."""
        order = []
        visited = set()
        temp_visited = set()

        def visit(name):
            if name in temp_visited:
                raise ValueError(f"Circular dependency detected: {name}")
            if name in visited:
                return
            
            temp_visited.add(name)
            instance = self.instances.get(name)
            if instance:
                for dep in instance.indicator.dependencies:
                    visit(dep)
            
            temp_visited.remove(name)
            visited.add(name)
            order.append(name)

        for name in self.instances:
            visit(name)
        return order

    def update(self, ts: datetime):
        self.last_accessed_at = datetime.now()
        results = {name: inst.last_result for name, inst in self.instances.items() if inst.last_result}
        
        for name in self.execution_order:
            instance = self.instances[name]
            context = IndicatorContext(
                ts=ts,
                input_mapping=instance.input_mapping,
                dependency_results=results
            )
            result = instance.indicator.update(context)
            instance.last_result = result
            results[name] = result

    def get_snapshot(self) -> dict[str, Any]:
        self.last_accessed_at = datetime.now()
        return {
            name: inst.last_result.value if inst.last_result else None 
            for name, inst in self.instances.items()
        }


class IndicatorRunner:
    """Manages multiple Pipelines and their lifecycles."""
    
    def __init__(self, data_manager: DataManager, ttl_seconds: int = 3600):
        self.data_manager = data_manager
        self.ttl_seconds = ttl_seconds
        self._pipelines: dict[str, Pipeline] = {}
        self._lock = Lock()

    def add_pipeline(self, name: str, indicator_configs: list[dict[str, Any]]):
        """
        indicator_configs format:
        [
            {
                "indicator": IndicatorObject,
                "mapping": {"slot_name": "provider:type:symbol"} 
                           # or {"slot_name": ["key1", "key2"]}
            },
            ...
        ]
        """
        instances = {}
        for cfg in indicator_configs:
            ind = cfg["indicator"]
            mapping = {}
            for slot, keys in cfg["mapping"].items():
                if isinstance(keys, (list, tuple)):
                    mapping[slot] = [self.data_manager.get_stream(k) for k in keys]
                else:
                    mapping[slot] = self.data_manager.get_stream(keys)
            
            instances[ind.name] = IndicatorInstance(indicator=ind, input_mapping=mapping)
            
        pipeline = Pipeline(name, instances)
        with self._lock:
            self._pipelines[name] = pipeline
        return pipeline

    def get_pipeline(self, name: str) -> Pipeline | None:
        with self._lock:
            return self._pipelines.get(name)

    def update_all(self, ts: datetime):
        """Update all active pipelines. Typically called on new bar/tick."""
        with self._lock:
            for pipeline in self._pipelines.values():
                pipeline.update(ts)

    def cleanup_expired(self):
        """Remove pipelines that haven't been accessed within TTL."""
        now = datetime.now()
        with self._lock:
            to_remove = [
                name for name, p in self._pipelines.items()
                if (now - p.last_accessed_at).total_seconds() > self.ttl_seconds
            ]
            for name in to_remove:
                del self._pipelines[name]
        return len(to_remove)
