"""FastAPI 应用入口。"""

from __future__ import annotations

import argparse

from fastapi import FastAPI

from sarap_engine import SPEC_VERSION, __version__
from sarap_engine.api.routes import router
from sarap_engine.api.service import EngineService
from sarap_engine.config import Settings, get_settings, reset_settings_cache
from sarap_engine.orchestration.store import JobStore
from sarap_engine.orchestration.worker import Worker


def create_app(settings: Settings | None = None, store: JobStore | None = None) -> FastAPI:
    settings = settings or get_settings()
    store = store or JobStore(settings.db_url)
    worker = Worker(store, settings)
    service = EngineService(store, settings, worker)

    app = FastAPI(
        title="SARAP Processing Engine",
        version=__version__,
        description=f"SARAP 第一版处理引擎内部 API（规范 {SPEC_VERSION}）。引擎不发布产品，不直接写平台业务库。",
    )
    app.state.settings = settings
    app.state.store = store
    app.state.worker = worker
    app.state.service = service
    app.state.internal_token = settings.inbound_token()
    app.include_router(router)

    @app.get("/")
    def root() -> dict[str, str]:
        return {"name": "sarap-engine", "version": __version__, "spec": SPEC_VERSION}

    return app


def cli() -> None:
    parser = argparse.ArgumentParser(description="启动 SARAP 处理引擎 API")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--mode", default=None, help="mock / snap / pie_sar")
    args = parser.parse_args()
    reset_settings_cache()
    settings = get_settings()
    if args.mode:
        settings.mode = args.mode
    host = args.host or settings.host
    port = args.port or settings.port
    import uvicorn

    uvicorn.run(create_app(settings), host=host, port=port)


if __name__ == "__main__":
    cli()
