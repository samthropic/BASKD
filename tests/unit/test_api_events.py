"""HTTP behaviour of ``/events`` and ``/health`` against the in-memory provider."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from baskd import __version__
from baskd.app import create_app
from baskd.errors import ALL_DAY_NOT_REPLACEABLE
from baskd.models import Event
from baskd.providers.memory import InMemoryCalendarProvider
from baskd.settings import Settings
from tests.conftest import event_payload


def create(client: TestClient, **overrides: Any) -> dict[str, Any]:
    response = client.post("/events", json=event_payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def test_health_reports_provider_and_version(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "provider": "memory", "version": __version__}


class TestCreate:
    def test_returns_201_with_location_and_utc_times(self, client: TestClient) -> None:
        response = client.post(
            "/events",
            json=event_payload(start="2026-10-07T11:00:00-04:00", end="2026-10-07T11:30:00-04:00"),
        )
        assert response.status_code == 201
        body = response.json()
        assert response.headers["Location"].endswith(f"/events/{body['id']}")
        assert body["start"] == "2026-10-07T15:00:00Z"
        assert body["end"] == "2026-10-07T15:30:00Z"
        assert body["title"] == "Sprint planning"
        assert body["description"] == "Bring the backlog"
        assert body["location"] == "Room 101"
        assert body["all_day"] is False

    def test_omitted_optional_fields_are_null(self, client: TestClient) -> None:
        payload = event_payload()
        payload.pop("description")
        payload.pop("location")

        response = client.post("/events", json=payload)

        assert response.status_code == 201
        body = response.json()
        assert body["description"] is None
        assert body["location"] is None
        assert body["web_link"] is None

    def test_created_event_is_retrievable(self, client: TestClient) -> None:
        created = create(client)
        fetched = client.get(f"/events/{created['id']}")
        assert fetched.status_code == 200
        assert fetched.json() == created

    def test_repeating_request_creates_distinct_events(self, client: TestClient) -> None:
        payload = event_payload()

        first = client.post("/events", json=payload)
        second = client.post("/events", json=payload)

        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json()["id"] != second.json()["id"]

    @pytest.mark.parametrize(
        ("overrides", "field"),
        [
            ({"title": ""}, "title"),
            ({"title": "   "}, "title"),
            ({"start": "2026-10-07T15:00:00"}, "start"),  # naive
            ({"end": "2026-10-07T15:00:00Z"}, None),  # end == start -> model-level error
            ({"end": "yesterday"}, "end"),
            ({"attendees": ["a@example.com"]}, "attendees"),
            ({"description": "x" * 8193}, "description"),
            ({"location": "x" * 1025}, "location"),
        ],
    )
    def test_invalid_input_is_422_with_details(
        self, client: TestClient, overrides: dict[str, Any], field: str | None
    ) -> None:
        response = client.post("/events", json=event_payload(**overrides))
        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "validation_error"
        locations = [detail["loc"] for detail in error["details"]]
        if field is None:
            assert ["body"] in locations
        else:
            assert ["body", field] in locations

    def test_missing_body_is_422(self, client: TestClient) -> None:
        response = client.post("/events")
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"

    def test_malformed_json_is_422(self, client: TestClient) -> None:
        response = client.post(
            "/events", content=b"{not json", headers={"content-type": "application/json"}
        )
        assert response.status_code == 422


class TestGet:
    def test_unknown_id_is_404(self, client: TestClient) -> None:
        response = client.get("/events/does-not-exist")
        assert response.status_code == 404
        assert response.json() == {
            "error": {"code": "event_not_found", "message": "Event 'does-not-exist' was not found"}
        }


class TestList:
    def test_empty(self, client: TestClient) -> None:
        response = client.get("/events")
        assert response.status_code == 200
        assert response.json() == {"items": [], "next_cursor": None}

    def test_window_and_ordering(self, client: TestClient) -> None:
        later = create(
            client, title="later", start="2026-10-07T17:00:00Z", end="2026-10-07T18:00:00Z"
        )
        earlier = create(client, title="earlier")
        create(client, title="next day", start="2026-10-08T09:00:00Z", end="2026-10-08T10:00:00Z")

        response = client.get(
            "/events", params={"from": "2026-10-07T00:00:00Z", "to": "2026-10-08T00:00:00Z"}
        )
        assert response.status_code == 200
        assert [item["id"] for item in response.json()["items"]] == [earlier["id"], later["id"]]

    def test_pagination_round_trip(self, client: TestClient) -> None:
        ids = [
            create(
                client, start=f"2026-10-07T{hour:02d}:00:00Z", end=f"2026-10-07T{hour:02d}:30:00Z"
            )["id"]
            for hour in (9, 10, 11)
        ]
        first = client.get("/events", params={"limit": 2}).json()
        assert [item["id"] for item in first["items"]] == ids[:2]
        assert first["next_cursor"] is not None

        second = client.get("/events", params={"limit": 2, "cursor": first["next_cursor"]}).json()
        assert [item["id"] for item in second["items"]] == ids[2:]
        assert second["next_cursor"] is None

    @pytest.mark.parametrize(
        "params",
        [
            {"from": "2026-10-08T00:00:00Z", "to": "2026-10-07T00:00:00Z"},  # inverted
            {"from": "2026-10-07T00:00:00"},  # naive
            {"limit": 0},
            {"limit": 251},
            {"limit": "many"},
            {"cursor": ""},
            {"frm": "2026-10-07T00:00:00Z"},  # typo: unknown params are rejected, not ignored
        ],
    )
    def test_invalid_query_is_422(self, client: TestClient, params: dict[str, Any]) -> None:
        response = client.get("/events", params=params)
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "validation_error"

    def test_malformed_cursor_is_400(self, client: TestClient) -> None:
        response = client.get("/events", params={"cursor": "garbage"})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_request"


class TestReplace:
    def test_replaces_all_editable_fields(self, client: TestClient) -> None:
        created = create(client)
        response = client.put(
            f"/events/{created['id']}",
            json={"title": "Moved", "start": "2026-10-08T15:00:00Z", "end": "2026-10-08T16:00:00Z"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == created["id"]
        assert body["title"] == "Moved"
        assert body["start"] == "2026-10-08T15:00:00Z"
        assert body["description"] is None  # omitted optional fields are cleared
        assert body["location"] is None
        assert client.get(f"/events/{created['id']}").json() == body

    def test_sets_then_clears_optional_fields(self, client: TestClient) -> None:
        created = create(client, description=None, location=None)
        url = f"/events/{created['id']}"
        filled = client.put(url, json=event_payload(description="Agenda", location="Lobby"))
        assert filled.status_code == 200
        assert (filled.json()["description"], filled.json()["location"]) == ("Agenda", "Lobby")
        # Explicit null and an empty string clear a field just like omitting it.
        cleared = client.put(url, json=event_payload(description=None, location=""))
        assert cleared.status_code == 200
        assert (cleared.json()["description"], cleared.json()["location"]) == (None, None)
        assert client.get(url).json() == cleared.json()

    def test_accepts_any_offset_and_returns_utc(self, client: TestClient) -> None:
        created = create(client)
        response = client.put(
            f"/events/{created['id']}",
            json=event_payload(start="2026-10-08T09:00:00-04:00", end="2026-10-08T09:30:00-04:00"),
        )
        assert response.status_code == 200
        assert response.json()["start"] == "2026-10-08T13:00:00Z"
        assert response.json()["end"] == "2026-10-08T13:30:00Z"

    def test_unknown_id_is_404(self, client: TestClient) -> None:
        response = client.put("/events/missing", json=event_payload())
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "event_not_found"

    def test_invalid_body_is_422_even_for_unknown_id(self, client: TestClient) -> None:
        response = client.put("/events/missing", json=event_payload(title=""))
        assert response.status_code == 422

    @pytest.mark.parametrize(
        "overrides",
        [
            {"title": "   "},  # blank after stripping
            {"start": "2026-10-07T15:00:00"},  # naive
            {"end": "2026-10-07T14:00:00Z"},  # end before start
            {"end": "2026-10-07T15:00:00Z"},  # end == start
            {"id": "someone-elses-id"},  # the id comes from the URL only
            {"all_day": True},  # read-only field
        ],
    )
    def test_invalid_body_is_422_and_event_is_unchanged(
        self, client: TestClient, overrides: dict[str, Any]
    ) -> None:
        created = create(client)
        response = client.put(f"/events/{created['id']}", json=event_payload(**overrides))
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"
        assert client.get(f"/events/{created['id']}").json() == created

    def test_missing_required_field_is_422(self, client: TestClient) -> None:
        created = create(client)
        body = event_payload()
        del body["end"]
        response = client.put(f"/events/{created['id']}", json=body)
        assert response.status_code == 422
        assert ["body", "end"] in [detail["loc"] for detail in response.json()["error"]["details"]]

    def test_all_day_event_is_400_and_unchanged(self) -> None:
        all_day = Event(
            id="holiday",
            title="Holiday",
            start=datetime(2026, 11, 26, tzinfo=UTC),
            end=datetime(2026, 11, 27, tzinfo=UTC),
            all_day=True,
        )
        provider = InMemoryCalendarProvider([all_day])
        app = create_app(settings=Settings(provider="memory", _env_file=None), provider=provider)
        with TestClient(app) as client:
            response = client.put("/events/holiday", json=event_payload())
            assert response.status_code == 400
            assert response.json()["error"] == {
                "code": "invalid_request",
                "message": ALL_DAY_NOT_REPLACEABLE,
            }
            assert client.get("/events/holiday").json()["all_day"] is True


class TestDelete:
    def test_delete_is_204_then_404(self, client: TestClient) -> None:
        created = create(client)
        assert client.delete(f"/events/{created['id']}").status_code == 204
        assert client.get(f"/events/{created['id']}").status_code == 404
        assert client.delete(f"/events/{created['id']}").status_code == 404

    def test_delete_does_not_affect_other_events(self, client: TestClient) -> None:
        keep = create(client, title="keep")
        drop = create(client, title="drop")
        client.delete(f"/events/{drop['id']}")
        listed = client.get("/events").json()["items"]
        assert [item["id"] for item in listed] == [keep["id"]]


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "http_error", "message": "Not Found"}}


def test_openapi_documents_error_envelope(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    create_op = schema["paths"]["/events"]["post"]
    assert "422" in create_op["responses"]
    assert "503" in create_op["responses"]
    assert "Repeating the request creates another event." in create_op["description"]
    location_header = create_op["responses"]["201"]["headers"]["Location"]
    assert location_header["schema"] == {"type": "string", "format": "uri"}
    assert "ErrorResponse" in schema["components"]["schemas"]
    list_params = {p["name"] for p in schema["paths"]["/events"]["get"]["parameters"]}
    assert {"from", "to", "limit", "cursor"} <= list_params
