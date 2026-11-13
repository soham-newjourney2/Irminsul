"""Uniform error envelope: {"error": {"code", "message", "details"}}. Never leaks stack traces."""

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("irminsul.errors")


class AppError(Exception):
    """Raise from services for expected, client-facing failures."""

    def __init__(
        self, status_code: int, code: str, message: str, details: Any | None = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def error_body(code: str, message: str, details: Any | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details}}


def _status_code_name(status: int) -> str:
    try:
        return HTTPStatus(status).name.lower()
    except ValueError:
        return "error"


async def _app_error(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):
        return await _unhandled_error(_, exc)
    return JSONResponse(error_body(exc.code, exc.message, exc.details), exc.status_code)


async def _http_error(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, StarletteHTTPException):
        return await _unhandled_error(_, exc)
    message = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
    return JSONResponse(
        error_body(_status_code_name(exc.status_code), message),
        exc.status_code,
        headers=exc.headers,
    )


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        return await _unhandled_error(_, exc)
    details = [
        {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
        for e in exc.errors()
    ]
    return JSONResponse(error_body("validation_error", "Invalid request", details), 422)


async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    log.exception("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(error_body("internal_error", "Internal server error"), 500)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unhandled_error)
