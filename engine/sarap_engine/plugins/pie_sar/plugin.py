"""PIE-SAR 预留接口。第一版 validate/run 明确未实现。"""

from __future__ import annotations

from sarap_engine.constants import EngineError, ErrorCode
from sarap_engine.plugins.base import PluginContext, PluginResult


class PieSarPlugin:
    name = "pie_sar"
    capabilities: list[str] = []

    def validate(self, context: PluginContext) -> None:
        raise EngineError(
            ErrorCode.PLUGIN_NOT_IMPLEMENTED,
            "pie_sar 插件在第一版中尚未实现，仅预留与 SNAP 相同的 ProcessingPlugin 接口。",
            retryable=False,
        )

    def run(self, context: PluginContext) -> PluginResult:
        self.validate(context)
        raise EngineError(  # pragma: no cover
            ErrorCode.PLUGIN_NOT_IMPLEMENTED,
            "pie_sar 插件在第一版中尚未实现。",
            retryable=False,
        )
