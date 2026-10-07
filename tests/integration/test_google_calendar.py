"""The thin slice, end to end, against the real Google Calendar.

Runs only when the environment (or ``.env``) configures ``BASKD_PROVIDER=google`` with
credentials; otherwise every test here is skipped with a reason. Each run tags its events
with a unique marker and deletes them afterwards, so concurrent runs on the shared test
calendar do not interfere.

    make test-integration        # or: uv run pytest -m integration
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from baskd.app import create_app
from baskd.settings import Settings

pytestmark = pytest.mark.integration


def _configured_settings() -> Settings | None:
    try:
        settings = Settings()  # reads BASKD_* env and .env
    except ValidationError:
        return None
    return settings if settings.provider == "google" else None


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    settings = _configured_settings()
    if settings is None:
        pytest.skip("BASKD_PROVIDER=google with credentials is not configured")
    with TestClient(create_app(settings=settings)) as test_client:
        yield test_client


@pytest.fixture
def cleanup(client: TestClient) -> Iterator[list[str]]:
    created: list[str] = []
    yield created
    for event_id in created:
        client.delete(f"/events/{event_id}")  # best effort; 404 is fine


def _window(start: datetime, hours: int = 2) -> dict[str, str]:
    return {
        "from": (start - timedelta(hours=hours)).isoformat().replace("+00:00", "Z"),
        "to": (start + timedelta(hours=hours)).isoformat().replace("+00:00", "Z"),
    }


def test_health_reports_google(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["provider"] == "google"


def test_create_get_list_replace_delete(client: TestClient, cleanup: list[str]) -> None:
    marker = uuid4().hex
    # Far enough in the future that human-created events on the test calendar never collide.
    start = (datetime.now(UTC) + timedelta(days=30)).replace(microsecond=0)
    end = start + timedelta(minutes=45)
    payload: dict[str, Any] = {
        "title": f"baskd-integration {marker}",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "description": "created by tests/integration; safe to delete",
        "location": "Nowhere in particular",
    }

    created = client.post("/events", json=payload)
    assert created.status_code == 201, created.text
    event = created.json()
    cleanup.append(event["id"])
    assert event["title"] == payload["title"]
    assert datetime.fromisoformat(event["start"]) == start
    assert datetime.fromisoformat(event["end"]) == end
    assert event["description"] == payload["description"]
    assert event["location"] == payload["location"]
    assert event["all_day"] is False
    assert event["web_link"], "Google events carry an htmlLink"
    assert created.headers["Location"].endswith(f"/events/{event['id']}")

    fetched = client.get(f"/events/{event['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == event

    listed = client.get("/events", params=_window(start))
    assert listed.status_code == 200, listed.text
    assert event["id"] in {item["id"] for item in listed.json()["items"]}

    outside = client.get("/events", params=_window(start + timedelta(days=5)))
    assert event["id"] not in {item["id"] for item in outside.json()["items"]}

    replaced = client.put(
        f"/events/{event['id']}",
        json={
            "title": f"baskd-integration {marker} moved",
            "start": (start + timedelta(hours=1)).isoformat(),
            "end": (end + timedelta(hours=1)).isoformat(),
        },
    )
    assert replaced.status_code == 200, replaced.text
    moved = replaced.json()
    assert moved["id"] == event["id"]
    assert moved["title"].endswith("moved")
    assert datetime.fromisoformat(moved["start"]) == start + timedelta(hours=1)
    assert moved["description"] is None  # omitted on PUT -> cleared at the provider too
    assert moved["location"] is None
    assert client.get(f"/events/{event['id']}").json() == moved

    assert client.delete(f"/events/{event['id']}").status_code == 204
    assert client.get(f"/events/{event['id']}").status_code == 404
    assert client.delete(f"/events/{event['id']}").status_code == 404


def test_replace_refuses_all_day_and_series_but_moves_one_occurrence(
    client: TestClient, cleanup: list[str]
) -> None:
    # The API cannot create all-day or recurring events, so seed them through the SDK.
    provider = client.app.state.provider  # type: ignore[attr-defined]
    marker = uuid4().hex
    day = (datetime.now(UTC) + timedelta(days=50)).date()
    start = datetime.combine(day, time(15), tzinfo=UTC)

    def insert(body: dict[str, Any]) -> dict[str, Any]:
        resource: dict[str, Any] = provider._execute(
            provider._events().insert(calendarId=provider._calendar_id, body=body)
        )
        cleanup.append(resource["id"])
        return resource

    all_day = insert(
        {
            "summary": f"baskd-integration {marker} all-day",
            "start": {"date": day.isoformat()},
            "end": {"date": (day + timedelta(days=1)).isoformat()},
        }
    )
    series = insert(
        {
            "summary": f"baskd-integration {marker} series",
            "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": (start + timedelta(minutes=30)).isoformat(), "timeZone": "UTC"},
            "recurrence": ["RRULE:FREQ=DAILY;COUNT=3"],
        }
    )
    new_start = start + timedelta(hours=2)
    body = {
        "title": f"baskd-integration {marker} moved",
        "start": new_start.isoformat(),
        "end": (new_start + timedelta(minutes=30)).isoformat(),
    }

    refused = client.put(f"/events/{all_day['id']}", json=body)
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["code"] == "invalid_request"
    assert client.get(f"/events/{all_day['id']}").json()["all_day"] is True

    refused = client.put(f"/events/{series['id']}", json=body)
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["code"] == "invalid_request"

    window = {"from": start.isoformat(), "to": (start + timedelta(days=3)).isoformat()}
    occurrences = [
        item
        for item in client.get("/events", params=window).json()["items"]
        if item["title"].endswith(f"{marker} series")
    ]
    assert len(occurrences) == 3
    moved = client.put(f"/events/{occurrences[0]['id']}", json=body)
    assert moved.status_code == 200, moved.text
    assert moved.json()["id"] == occurrences[0]["id"]
    assert datetime.fromisoformat(moved.json()["start"]) == new_start
    untouched = client.get(f"/events/{occurrences[1]['id']}").json()
    assert untouched["title"].endswith(f"{marker} series")


def test_unknown_event_is_404(client: TestClient) -> None:
    response = client.get("/events/definitelynotanevent000")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "event_not_found"


def test_pagination_cursor_round_trip(client: TestClient, cleanup: list[str]) -> None:
    marker = uuid4().hex
    base = (datetime.now(UTC) + timedelta(days=40)).replace(microsecond=0)
    ids: list[str] = []
    for index in range(3):
        start = base + timedelta(hours=index)
        response = client.post(
            "/events",
            json={
                "title": f"baskd-integration {marker} #{index}",
                "start": start.isoformat(),
                "end": (start + timedelta(minutes=30)).isoformat(),
            },
        )
        assert response.status_code == 201, response.text
        ids.append(response.json()["id"])
        cleanup.append(ids[-1])

    window = _window(base + timedelta(hours=1), hours=2)
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(10):  # bounded: a broken cursor must not loop forever
        params: dict[str, Any] = {**window, "limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = client.get("/events", params=params)
        assert page.status_code == 200, page.text
        body = page.json()
        seen.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert [event_id for event_id in seen if event_id in ids] == ids
