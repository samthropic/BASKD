"""Level 5: every failure reaches the caller as the documented error and leaves one log line.

Each test checks the public response first, then the ``request_failed`` line: operation,
error category, whether the provider was involved, status and request id (spec 5.5).
Failures are produced deterministically with the in-memory provider or ``FailingProvider``.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from baskd.errors import (
    CalendarError,
    EventNotFound,
    InvalidRequest,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailable,
)
from tests.conftest import event_payload, failing_client

GENERATED_ID = re.compile(r"[0-9a-f]{32}")


@pytest.fixture
def failure_log(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    with caplog.at_level(logging.INFO, logger="baskd"):
        yield caplog


def failures(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    return [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "baskd.api.failures"
    ]


def only_failure(caplog: pytest.LogCaptureFixture) -> dict[str, Any]:
    lines = failures(caplog)
    assert len(lines) == 1, lines
    return lines[0]


# -- the four cases spec 5.6 asks for ---------------------------------------------------------


def test_success_logs_no_failure_and_carries_a_request_id(
    client: TestClient, failure_log: pytest.LogCaptureFixture
) -> None:
    response = client.post("/events", json=event_payload())
    assert response.status_code == 201
    assert GENERATED_ID.fullmatch(response.headers["X-Request-ID"])
    assert failures(failure_log) == []


def test_invalid_input_never_reaches_the_provider(
    client: TestClient, failure_log: pytest.LogCaptureFixture
) -> None:
    response = client.post("/events", json=event_payload(end="2026-10-07T14:00:00Z"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert only_failure(failure_log) == {
        "event": "request_failed",
        "operation": "create_event",
        "status": 422,
        "error": "validation_error",
        "category": "invalid_input",
        "provider_involved": False,
        "retryable": False,
        "method": "POST",
        "route": "/events",
        "request_id": response.headers["X-Request-ID"],
    }


def test_missing_event_is_reported_by_the_provider(
    client: TestClient, failure_log: pytest.LogCaptureFixture
) -> None:
    response = client.get("/events/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "event_not_found"
    line = only_failure(failure_log)
    assert line["operation"] == "get_event"
    assert line["route"] == "/events/{event_id}"  # the template: event ids are not logged
    assert line["category"] == "not_found"
    assert line["provider_involved"] is True
    assert failure_log.records[-1].levelno == logging.WARNING


def test_provider_failure_is_503_retryable_and_logged_as_error(
    failure_log: pytest.LogCaptureFixture,
) -> None:
    response = failing_client(ProviderUnavailable("down")).get("/events")
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
    assert response.json()["error"]["code"] == "provider_unavailable"
    line = only_failure(failure_log)
    assert line["operation"] == "list_events"
    assert line["category"] == "provider_failure"
    assert line["provider_involved"] is True
    assert line["retryable"] is True
    record = next(r for r in failure_log.records if r.name == "baskd.api.failures")
    assert record.levelno == logging.ERROR
    assert record.exc_info is None  # an expected failure: no stack trace


# -- every error class: category and retry guidance ---------------------------------------------


@pytest.mark.parametrize(
    ("error", "status", "category", "retryable"),
    [
        (EventNotFound("e1"), 404, "not_found", False),
        (InvalidRequest("bad"), 400, "invalid_input", False),
        (ProviderAuthError("denied"), 502, "access_denied", False),
        (ProviderUnavailable("down"), 503, "provider_failure", True),
        (ProviderError("weird"), 502, "provider_failure", False),
        (CalendarError("unknown"), 500, "internal", False),
    ],
)
def test_each_error_class_is_categorised(
    failure_log: pytest.LogCaptureFixture,
    error: CalendarError,
    status: int,
    category: str,
    retryable: bool,
) -> None:
    response = failing_client(error).delete("/events/e1")
    assert response.status_code == status
    line = only_failure(failure_log)
    assert (line["status"], line["error"]) == (status, error.code)
    assert (line["category"], line["retryable"]) == (category, retryable)
    assert line["operation"] == "delete_event"


# -- request ids ------------------------------------------------------------------------------


def test_callers_request_id_is_echoed_and_logged(
    client: TestClient, failure_log: pytest.LogCaptureFixture
) -> None:
    response = client.get("/events/nope", headers={"X-Request-ID": "trace-42.a:b"})
    assert response.headers["X-Request-ID"] == "trace-42.a:b"
    assert only_failure(failure_log)["request_id"] == "trace-42.a:b"


@pytest.mark.parametrize("unsafe", ["has spaces", "x" * 129, "line\\nbreak", "{json}"])
def test_malformed_request_id_is_replaced(client: TestClient, unsafe: str) -> None:
    response = client.get("/health", headers={"X-Request-ID": unsafe})
    assert GENERATED_ID.fullmatch(response.headers["X-Request-ID"])


# -- failures raised before or outside the provider -----------------------------------------


def test_rejected_cursor_does_not_involve_the_provider(
    client: TestClient, failure_log: pytest.LogCaptureFixture
) -> None:
    response = client.get("/events", params={"cursor": "garbage"})
    assert response.status_code == 400
    line = only_failure(failure_log)
    assert (line["category"], line["provider_involved"]) == ("invalid_input", False)


def test_unknown_route_is_logged_without_an_operation(
    client: TestClient, failure_log: pytest.LogCaptureFixture
) -> None:
    response = client.get("/nope")
    assert response.status_code == 404
    line = only_failure(failure_log)
    assert (line["operation"], line["route"], line["category"]) == ("unknown", None, "not_found")


def test_bug_is_a_generic_500_with_a_logged_traceback(
    failure_log: pytest.LogCaptureFixture,
) -> None:
    response = failing_client(RuntimeError("secret internal detail")).get("/events/e1")
    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "Internal server error"}
    }
    assert "secret" not in response.text
    assert GENERATED_ID.fullmatch(response.headers["X-Request-ID"])
    record = next(r for r in failure_log.records if r.name == "baskd.api.failures")
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None
    assert json.loads(record.getMessage())["category"] == "internal"


# -- what must never be logged ----------------------------------------------------------------


def test_failure_logs_hold_no_event_content_or_ids(
    client: TestClient, failure_log: pytest.LogCaptureFixture
) -> None:
    client.post(
        "/events",
        json=event_payload(description="secret agenda", end="2026-10-07T14:00:00Z"),
    )
    client.put("/events/private-id-7", json=event_payload(title="secret title"))
    client.get("/events", params={"from": "secret-not-a-time"})

    assert len(failures(failure_log)) == 3
    assert "secret" not in failure_log.text
    assert "private-id-7" not in failure_log.text
    assert all(record.exc_info is None for record in failure_log.records)
