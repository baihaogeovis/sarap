"""引擎环境与默认配置。CRS / 网格等均可配，不写死唯一试点。"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _first_env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return ""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SARAP_ENGINE_",
        env_file=".env",
        extra="ignore",
    )

    mode: str = Field(default="mock", description="默认执行模式：mock / snap / pie_sar")
    host: str = "0.0.0.0"
    port: int = 8081
    work_dir: Path = Path("./data/engine-work")
    db_url: str = "sqlite:///./data/engine-jobs.sqlite"
    platform_base_url: str = "http://localhost:8000"
    platform_ingest_url: str = "http://localhost:8000/api/v1/internal/products"
    platform_token: str = ""  # 服务账号明文 API Key，回传时只放 X-API-Key，不要放进 Bearer
    internal_token: str = ""  # 兼容旧变量 SARAP_ENGINE_INTERNAL_TOKEN；优先用平台同名变量

    def inbound_token(self) -> str:
        """平台调用引擎：对齐 SARAP_ENGINE_TOKEN（X-Internal-Token 或 Bearer）。"""
        return _first_env("SARAP_ENGINE_TOKEN") or self.internal_token

    def outbound_internal_token(self) -> str:
        """引擎回传平台：X-Internal-Token 对齐平台的 SARAP_INTERNAL_TOKEN。"""
        return _first_env("SARAP_INTERNAL_TOKEN") or self.internal_token
    ingest_mode: str = Field(
        default="http",
        description="http 走平台入库；mock 仅写本地回执，便于无平台空跑",
    )

    # 分析默认值，可被试点配置覆盖
    default_crs: str = "EPSG:4548"
    default_exchange_crs: str = "EPSG:4490"
    pixel_spacing_m: float = 10.0
    grid_origin_x: float = 0.0
    grid_origin_y: float = 0.0

    max_retries: int = 3
    snap_crash_immediate_retries: int = 1
    retry_base_seconds: float = 2.0
    retry_max_seconds: float = 60.0
    gpt_timeout_seconds: float = 2400.0
    gpt_binary: str = "gpt"

    min_valid_coverage_ratio: float = 0.05
    min_dem_coverage_ratio: float = 0.80

    # 测试或 demo 时同步跑完任务，不启后台线程
    run_inline: bool = False
    # python -m sarap_engine.main 时是否后台消费队列。create_app 本身不启动线程。
    worker: bool = True

    def resolved_work_dir(self) -> Path:
        path = self.work_dir
        if not path.is_absolute():
            path = Path.cwd() / path
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
