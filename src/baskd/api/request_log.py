"""Request ids, a server span and one structured log line per request.

Every response carries an ``X-Request-ID`` header: the caller's own id when it sent a
well-formed one, otherwise a fresh one. :func:`observe_request` wraps each request in a span
(continuing the caller's ``traceparent``, which Cloud Run sends) and, when the response is
ready, writes one JSON line, for example::

    {"event": "request_failed", "operation": "get_event", "outcome": "failure",
     "status": 404, "error": "not_found", "category": "not_found",
     "provider_involved": true, "retryable": false, "method": "GET",
     "route": "/events/{event_id}", "request_id": "6f1c...", "latency_ms": 212.4,
     "release": "0.2.0+1a2b3c4", "trace_id": "4bf9...", "span_id": "00f0..."}

A success is the same line with ``"event": "request_succeeded"``, ``"outcome": "success"``
and no ``error``/``category``/``retryable``. The error handlers record the failure with
:func:`log_failure`; this module writes the line, so there is exactly one per request.
``/health`` is not logged or traced: Cloud Run probes it every 30 seconds.

What is deliberately *not* logged or put on spans: request and response bodies (event
content), query strings, the concrete path (it holds event ids), headers, credentials and
provider error text. Successes are ``INFO``, expected failures (4xx) ``WARNING`` without a
stack trace, 5xx ``ERROR``; only a bug (``internal_error``) carries a traceback.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from fastapi import Request, Response
from opentelemetry import propagate, trace
from opentelemetry.trace import Span, SpanKind, StatusCode, format_span_id, format_trace_id

logger = logging.getLogger("baskd.requests")
_tracer = trace.get_tracer(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
_WELL_FORMED_REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")
_NOT_OBSERVED = frozenset({"/health"})


async def observe_request(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """HTTP middleware: request id, server span, and the request's log line."""
    incoming = request.headers.get(REQUEST_ID_HEADER, "")
    request.state.request_id = (
        incoming if _WELL_FORMED_REQUEST_ID.fullmatch(incoming) else uuid4().hex
    )
    if request.url.path in _NOT_OBSERVED:
        response = await call_next(request)
    else:
        response = await _observed(request, call_next)
    response.headers[REQUEST_ID_HEADER] = request.state.request_id
    return response


async def _observed(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    started = time.perf_counter()
    # Our own status handling: the default would copy exception text (event ids) into spans.
    with _tracer.start_as_current_span(
        request.method,
        context=propagate.extract(request.headers),
        kind=SpanKind.SERVER,
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            response = await call_next(request)
        except Exception as exc:
            # A bug. The catch-all handler (outside this middleware) turns it into the 500.
            log_failure(
                request, status=500, error="internal_error", category="internal", retryable=False
            )
            _finish(request, span, 500, started, exc_info=exc)
            raise
        _finish(request, span, response.status_code, started)
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
) -> None:
    """Record why the request failed; its log line carries these fields."""
    request.state.failure = {
        "status": status,
        "error": error,
        "category": category,
        "retryable": retryable,
    }


def _finish(
    request: Request,
    span: Span,
    status: int,
    started: float,
    exc_info: BaseException | None = None,
) -> None:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    failure: dict[str, Any] | None = getattr(request.state, "failure", None)

    span.update_name(f"{request.method} {route_path}" if route_path else request.method)
    span.set_attribute("http.request.method", request.method)
    span.set_attribute("http.response.status_code", status)
    if route_path:
        span.set_attribute("http.route", route_path)
    if failure:
        span.set_attribute("baskd.error", failure["error"])
        span.set_status(StatusCode.ERROR, failure["error"])
    context = span.get_span_context()

    fields: dict[str, Any] = {
        "event": "request_failed" if failure else "request_succeeded",
        "operation": getattr(route, "name", None) or "unknown",
        "outcome": "failure" if failure else "success",
        "status": status,
    }
    if failure:
        fields |= {k: failure[k] for k in ("error", "category")}
    fields["provider_involved"] = bool(getattr(request.state, "provider_called", False))
    if failure:
        fields["retryable"] = failure["retryable"]
    fields |= {
        "method": request.method,
        "route": route_path,
        "request_id": request_id_of(request),
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "release": getattr(request.app.state, "release", None),
        "trace_id": format_trace_id(context.trace_id),
        "span_id": format_span_id(context.span_id),
    }
    level = logging.INFO
    if failure:
        level = logging.ERROR if status >= 500 else logging.WARNING
    logger.log(level, json.dumps(fields), exc_info=exc_info, extra={"fields": fields})
