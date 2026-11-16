from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def ok(data: Any = None, meta: dict[str, Any] | None = None, status_code: int = 200) -> JSONResponse:
    return JSONResponse({"data": data, "error": None, "meta": meta or {}}, status_code=status_code)


def err(code: str, message: str, status_code: int, details: Any = None) -> JSONResponse:
    return JSONResponse(
        {"data": None, "error": {"code": code, "message": message, "details": details}, "meta": {}},
        status_code=status_code,
    )


class APIError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: Any = None) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def register_exception_handlers(app) -> None:
    @app.exception_handler(APIError)
    async def _api_error(_: Request, exc: APIError) -> JSONResponse:
        return err(exc.code, exc.message, exc.status_code, exc.details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found"}.get(exc.status_code, "http_error")
        return err(code, str(exc.detail), exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _valid(_: Request, exc: RequestValidationError) -> JSONResponse:
        return err("validation_error", "Request validation failed", 422, exc.errors())
