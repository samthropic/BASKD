"""One public read contract across adapters; Google uses an offline SDK double."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from baskd.app import create_app
from baskd.models import Event
from baskd.ports import CalendarProvider
from baskd.providers.google import GoogleCalendarProvider
from baskd.providers.memory import InMemoryCalendarProvider
from baskd.settings import Settings
from tests.unit.test_google_provider import (
    CALENDAR_ID,
    GOOGLE_EVENT,
    FakeCredentials,
    FakeEvents,
    FakeService,
    http_error,
)


@pytest.fixture(params=["memory", "google"])
def backend(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def read_provider(backend: str, resource: dict[str, Any]) -> CalendarProvider:
    """Seed equivalent input without using either adapter's output mapper as an oracle."""
    if backend == "memory":
        all_day = "date" in resource["start"]
        start = (
            resource["start"]["date"] + "T00:00:00Z" if all_day else resource["start"]["dateTime"]
        )
        end = resource["end"]["date"] + "T00:00:00Z" if all_day else resource["end"]["dateTime"]
        return InMemoryCalendarProvider(
            [
                Event(
                    id=resource["id"],
                    title=resource.get("summary", ""),
                    start=start,
                    end=end,
                    all_day=all_day,
                    description=resource.get("description"),
                    location=resource.get("location"),
                    web_link=resource.get("htmlLink"),
                )
            ]
        )
    events = FakeEvents()
    events.enqueue("get", resource, resource)
    return GoogleCalendarProvider(FakeCredentials(), CALENDAR_ID, service=FakeService(events))


def client_for(provider: CalendarProvider) -> TestClient:
    return TestClient(create_app(settings=Settings(_env_file=None), provider=provider))


@pytest.mark.parametrize("kind", ["timed", "all-day", "occurrence", "minimal"])
def test_read_contract(backend: str, kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    resource = dict(GOOGLE_EVENT)
    if kind == "all-day":
        resource.update(start={"date": "2026-10-07"}, end={"date": "2026-10-08"})
    elif kind == "occurrence":
        resource["recurringEventId"] = "series"
    elif kind == "minimal":
        for key in ("summary", "description", "location", "htmlLink"):
            resource.pop(key)
    provider = read_provider(backend, resource)

    def unexpected_build(_: Settings) -> CalendarProvider:
        raise AssertionError("Injected providers must bypass the configured factory")

    monkeypatch.setattr("baskd.app.build_provider", unexpected_build)
    with client_for(provider) as client:
        first = client.get(f"/events/{resource['id']}")
        second = client.get(f"/events/{resource['id']}")
        assert first.status_code == second.status_code == 200
        assert (
            first.json()
            == second.json()
            == {
                "id": resource["id"],
                "title": "" if kind == "minimal" else "Sprint planning",
                "start": "2026-10-07T00:00:00Z" if kind == "all-day" else "2026-10-07T15:00:00Z",
                "end": "2026-10-08T00:00:00Z" if kind == "all-day" else "2026-10-07T15:30:00Z",
                "all_day": kind == "all-day",
                "description": None if kind == "minimal" else "Bring the backlog",
                "location": None if kind == "minimal" else "Room 101",
                "web_link": None if kind == "minimal" else GOOGLE_EVENT["htmlLink"],
            }
        )
        assert client.get("/health").json()["provider"] == backend


@pytest.mark.parametrize("outcome", [404, 410, "cancelled"])
def test_missing_or_deleted_is_404(backend: str, outcome: int | str) -> None:
    provider: CalendarProvider = InMemoryCalendarProvider()
    if backend == "google":
        events = FakeEvents()
        events.enqueue(
            "get",
            {**GOOGLE_EVENT, "status": "cancelled"}
            if outcome == "cancelled"
            else http_error(int(outcome)),
        )
        provider = GoogleCalendarProvider(
            FakeCredentials(), CALENDAR_ID, service=FakeService(events)
        )
    with client_for(provider) as client:
        response = client.get("/events/gone")
        assert response.status_code == 404
        assert response.json() == {
            "error": {"code": "not_found", "message": "Event 'gone' was not found"}
        }


@pytest.mark.parametrize(
    ("status", "expected", "code"),
    [
        (401, 502, "access_denied"),
        (403, 502, "access_denied"),
        (429, 503, "provider_unavailable"),
        (503, 503, "provider_unavailable"),
    ],
)
def test_google_failures_through_http(status: int, expected: int, code: str) -> None:
    events = FakeEvents()
    events.enqueue("get", http_error(status))
    provider = GoogleCalendarProvider(FakeCredentials(), CALENDAR_ID, service=FakeService(events))
    with client_for(provider) as client:
        response = client.get("/events/e1")
        assert response.status_code == expected
        assert response.json()["error"]["code"] == code
        if expected == 503:
            assert response.headers["Retry-After"] == "5"


def test_invalid_id_is_rejected_before_provider_call(backend: str) -> None:
    # No Google outcomes queued: an accidental provider call fails the test.
    provider: CalendarProvider = InMemoryCalendarProvider()
    if backend == "google":
        provider = GoogleCalendarProvider(
            FakeCredentials(), CALENDAR_ID, service=FakeService(FakeEvents())
        )
    with client_for(provider) as client:
        response = client.get("/events/" + "a" * 1025)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_input"


def test_two_apps_keep_their_own_provider() -> None:
    first_provider = read_provider("memory", GOOGLE_EVENT)
    with client_for(first_provider) as first, client_for(InMemoryCalendarProvider()) as second:
        assert first.get("/events/abc123def456").status_code == 200
        assert second.get("/events/abc123def456").status_code == 404
        assert first.get("/events/abc123def456").status_code == 200


def test_get_openapi_documents_contract() -> None:
    with client_for(InMemoryCalendarProvider()) as client:
        operation = client.get("/openapi.json").json()["paths"]["/events/{event_id}"]["get"]
        assert set(operation["responses"]) == {"200", "404", "422", "502", "503"}
        assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/Event"
        }
        assert "without changing it" in operation["description"]
