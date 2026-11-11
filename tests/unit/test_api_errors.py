"""Provider failures reach clients as the documented envelope, never as stack traces."""

from __future__ import annotations

import pytest

from baskd import __version__
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
    ("error", "status", "code", "retryable"),
    [
        (EventNotFound("e1"), 404, "not_found", False),
        (InvalidRequest("bad cursor"), 400, "invalid_input", False),
        (ProviderUnavailable("down"), 503, "provider_unavailable", True),
        (ProviderAuthError("denied"), 403, "access_denied", False),
        (ProviderError("weird"), 502, "provider_error", False),
        (CalendarError("unknown"), 500, "calendar_error", False),
    ],
)
def test_domain_errors_map_to_status_code_and_retryable(
    error: CalendarError, status: int, code: str, retryable: bool
) -> None:
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
        assert body["error"]["retryable"] is retryable
        assert "details" not in body["error"]


def test_unavailable_includes_retry_after() -> None:
    response = failing_client(ProviderUnavailable("down")).get("/events")
    assert response.headers["Retry-After"] == "5"


def test_unexpected_exception_is_generic_500() -> None:
    response = failing_client(RuntimeError("secret internal detail")).get("/events")
    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "Internal server error", "retryable": False}
    }
    assert "secret" not in response.text


def test_health_does_not_touch_the_provider() -> None:
    response = failing_client(ProviderUnavailable("down")).get("/health")
    assert response.status_code == 200
    assert response.json()["provider"] == "failing"


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (ProviderUnavailable("down"), "provider_unavailable"),
        (ProviderAuthError("calendar not shared"), "access_denied"),
    ],
)
def test_ready_is_503_while_health_stays_200(error: CalendarError, reason: str) -> None:
    # The split that keeps a provider outage from becoming a restart loop: probes use
    # /health, which stays up; /ready reports that requests would fail right now.
    client = failing_client(error)
    assert client.get("/health").status_code == 200
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "provider": "failing",
        "version": __version__,
        "reason": reason,
    }
    assert error.message not in response.text
