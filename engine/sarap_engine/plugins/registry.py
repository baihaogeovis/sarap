"""插件注册表。"""

from __future__ import annotations

from typing import Callable

from sarap_engine.constants import EngineError, ErrorCode, ExecutionMode
from sarap_engine.plugins.base import ProcessingPlugin


class PluginRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, Callable[[], ProcessingPlugin]] = {}

    def register(self, name: str, factory: Callable[[], ProcessingPlugin]) -> None:
        self._factories[name] = factory

    def create(self, name: str) -> ProcessingPlugin:
        if name not in self._factories:
            raise EngineError(
                ErrorCode.PLUGIN_NOT_IMPLEMENTED,
                f"未知处理插件: {name}",
                retryable=False,
            )
        return self._factories[name]()

    def names(self) -> list[str]:
        return sorted(self._factories)


_REGISTRY: PluginRegistry | None = None


def default_registry() -> PluginRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        from sarap_engine.plugins.mock.plugin import MockPlugin
        from sarap_engine.plugins.pie_sar.plugin import PieSarPlugin
        from sarap_engine.plugins.snap.plugin import SnapPlugin

        reg = PluginRegistry()
        reg.register(ExecutionMode.MOCK.value, MockPlugin)
        reg.register(ExecutionMode.SNAP.value, SnapPlugin)
        reg.register(ExecutionMode.PIE_SAR.value, PieSarPlugin)
        _REGISTRY = reg
    return _REGISTRY
