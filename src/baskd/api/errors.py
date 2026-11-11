"""One error envelope for every failure the API can report.

Every non-2xx response has the body::

    {"error": {"code": "<stable_snake_case>", "message": "<human readable>", "details": [...]}}

``details`` is only present for validation errors and lists ``loc``/``msg``/``type`` per
problem, without echoing the submitted input back.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from baskd.api.failure_log import REQUEST_ID_HEADER, log_failure, request_id_of
from baskd.errors import (
    CalendarError,
    EventNotFound,
    InvalidRequest,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailable,
)

#: Which HTTP status each domain error maps to. Most specific first; the base class last.
STATUS_BY_ERROR: dict[type[CalendarError], int] = {
    EventNotFound: status.HTTP_404_NOT_FOUND,
    InvalidRequest: status.HTTP_400_BAD_REQUEST,
    ProviderUnavailable: status.HTTP_503_SERVICE_UNAVAILABLE,
    ProviderAuthError: status.HTTP_502_BAD_GATEWAY,
    ProviderError: status.HTTP_502_BAD_GATEWAY,
    CalendarError: status.HTTP_500_INTERNAL_SERVER_ERROR,
}

RETRY_AFTER_SECONDS = "5"


class ValidationDetail(BaseModel):
    loc: list[str | int]
    msg: str
    type: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ValidationDetail] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


def error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    details: Sequence[ValidationDetail] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message, details=list(details) if details else None)
    )
    return JSONResponse(
        status_code=status_code, content=body.model_dump(exclude_none=True), headers=headers
    )


def status_for(exc: CalendarError) -> int:
    for klass, status_code in STATUS_BY_ERROR.items():
        if isinstance(exc, klass):
            return status_code
    return status.HTTP_500_INTERNAL_SERVER_ERROR  # pragma: no cover


def _validation_details(errors: Sequence[Any]) -> list[ValidationDetail]:
    return [
        ValidationDetail(
            loc=[part for part in err.get("loc", ()) if isinstance(part, str | int)],
            msg=str(err.get("msg", "")),
            type=str(err.get("type", "")),
        )
        for err in errors
    ]


def register_error_handlers(app: FastAPI) -> None:
    """Attach the handlers to ``app``. Called once from :func:`baskd.app.create_app`."""

    @app.exception_handler(CalendarError)
    async def handle_calendar_error(request: Request, exc: CalendarError) -> JSONResponse:
        status_code = status_for(exc)
        log_failure(
            request,
            status=status_code,
            error=exc.code,
            category=exc.category,
            retryable=exc.retryable,
        )
        headers = (
            {"Retry-After": RETRY_AFTER_SECONDS}
            if status_code == status.HTTP_503_SERVICE_UNAVAILABLE
            else None
        )
        return error_response(status_code, exc.code, exc.message, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _validation_failed(request, exc.errors())

    @app.exception_handler(ValidationError)
    async def handle_model_validation(request: Request, exc: ValidationError) -> JSONResponse:
        return _validation_failed(request, exc.errors())

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        log_failure(
            request,
            status=exc.status_code,
            error="http_error",
            category="not_found" if exc.status_code == 404 else "invalid_input",
            retryable=False,
        )
        message = exc.detail if isinstance(exc.detail, str) else "HTTP error"
        return error_response(exc.status_code, "http_error", message, headers=exc.headers)

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # A bug, so the traceback is logged. This handler runs outside the middleware
        # stack, so it must add the request id header itself.
        log_failure(
            request,
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error="internal_error",
            category="internal",
            retryable=False,
            exc_info=exc,
        )
        request_id = request_id_of(request)
        return error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_error",
            "Internal server error",
            headers={REQUEST_ID_HEADER: request_id} if request_id else None,
        )


def _validation_failed(request: Request, errors: Sequence[Any]) -> JSONResponse:
    log_failure(
        request,
        status=status.HTTP_422_UNPROCESSABLE_CONTENT,
        error="invalid_input",
        category="invalid_input",
        retryable=False,
    )
    return error_response(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "invalid_input",
        "Request validation failed",
        details=_validation_details(errors),
    )


def documented_errors(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """``responses=`` entry for route decorators so the envelope shows up in OpenAPI."""
    return {code: {"model": ErrorResponse} for code in status_codes}
