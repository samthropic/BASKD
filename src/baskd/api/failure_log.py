"""Request ids and one structured log line per failed request.

Every response carries an ``X-Request-ID`` header: the caller's own id when it sent a
well-formed one, otherwise a fresh one. When a request fails, :func:`log_failure` writes a
single JSON log line a teammate can search for, for example::

    {"event": "request_failed", "operation": "get_event", "status": 404,
     "error": "not_found", "category": "not_found", "provider_involved": true,
     "retryable": false, "method": "GET", "route": "/events/{event_id}",
     "request_id": "6f1c..."}

What is deliberately *not* logged: request and response bodies (event content), query
strings, the concrete path (it holds event ids), headers, credentials and provider error
text. Expected failures (4xx) are ``WARNING`` without a stack trace; 5xx are ``ERROR``, and
only a bug (``internal_error``) carries a traceback.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import Request, Response

logger = logging.getLogger("baskd.api.failures")

REQUEST_ID_HEADER = "X-Request-ID"
_WELL_FORMED_REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")


async def assign_request_id(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """HTTP middleware: adopt or create the request id and echo it on the response."""
    incoming = request.headers.get(REQUEST_ID_HEADER, "")
    request.state.request_id = (
        incoming if _WELL_FORMED_REQUEST_ID.fullmatch(incoming) else uuid4().hex
    )
    response = await call_next(request)
    response.headers[REQUEST_ID_HEADER] = request.state.request_id
    return response


def request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def log_failure(
    request: Request,
    *,
    status: int,
    error: str,
    category: str,
    retryable: bool,
    exc_info: BaseException | None = None,
) -> None:
    """Write the ``request_failed`` line for a response the API is about to send."""
    route = request.scope.get("route")
    fields = {
        "event": "request_failed",
        "operation": getattr(route, "name", None) or "unknown",
        "status": status,
        "error": error,
        "category": category,
        "provider_involved": bool(getattr(request.state, "provider_called", False)),
        "retryable": retryable,
        "method": request.method,
        "route": getattr(route, "path", None),
        "request_id": request_id_of(request),
    }
    level = logging.ERROR if status >= 500 else logging.WARNING
    logger.log(level, json.dumps(fields), exc_info=exc_info)
