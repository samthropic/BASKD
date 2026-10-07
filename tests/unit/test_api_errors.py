"""Provider failures reach clients as the documented envelope, never as stack traces."""

from __future__ import annotations

import pytest

from baskd.errors import (
    CalendarError,
    EventNotFound,
    InvalidRequest,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailable,
)
from tests.conftest import event_payload, failing_client


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (EventNotFound("e1"), 404, "event_not_found"),
        (InvalidRequest("bad cursor"), 400, "invalid_request"),
        (ProviderUnavailable("down"), 503, "provider_unavailable"),
        (ProviderAuthError("denied"), 502, "provider_auth_error"),
        (ProviderError("weird"), 502, "provider_error"),
        (CalendarError("unknown"), 500, "calendar_error"),
    ],
)
def test_domain_errors_map_to_status_and_code(error: CalendarError, status: int, code: str) -> None:
    client = failing_client(error)
    for response in (
        client.get("/events"),
        client.get("/events/e1"),
        client.post("/events", json=event_payload()),
        client.put("/events/e1", json=event_payload()),
        client.delete("/events/e1"),
    ):
        assert response.status_code == status, response.text
        body = response.json()
        assert body["error"]["code"] == code
        assert body["error"]["message"] == error.message
        assert "details" not in body["error"]


def test_unavailable_includes_retry_after() -> None:
    response = failing_client(ProviderUnavailable("down")).get("/events")
    assert response.headers["Retry-After"] == "5"


def test_unexpected_exception_is_generic_500() -> None:
    response = failing_client(RuntimeError("secret internal detail")).get("/events")
    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "Internal server error"}
    }
    assert "secret" not in response.text


def test_health_does_not_touch_the_provider() -> None:
    response = failing_client(ProviderUnavailable("down")).get("/health")
    assert response.status_code == 200
    assert response.json()["provider"] == "failing"
