"""HTTP behaviour of ``/events`` and ``/health`` against the in-memory provider."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from baskd import __version__
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
        assert body["all_day"] is False

    def test_created_event_is_retrievable(self, client: TestClient) -> None:
        created = create(client)
        fetched = client.get(f"/events/{created['id']}")
        assert fetched.status_code == 200
        assert fetched.json() == created

    @pytest.mark.parametrize(
        ("overrides", "field"),
        [
            ({"title": ""}, "title"),
            ({"start": "2026-10-07T15:00:00"}, "start"),  # naive
            ({"end": "2026-10-07T15:00:00Z"}, None),  # end == start -> model-level error
            ({"end": "yesterday"}, "end"),
            ({"attendees": ["a@example.com"]}, "attendees"),
            ({"description": "x" * 8193}, "description"),
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

    def test_unknown_id_is_404(self, client: TestClient) -> None:
        response = client.put("/events/missing", json=event_payload())
        assert response.status_code == 404

    def test_invalid_body_is_422_even_for_unknown_id(self, client: TestClient) -> None:
        response = client.put("/events/missing", json=event_payload(title=""))
        assert response.status_code == 422


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
    assert "ErrorResponse" in schema["components"]["schemas"]
    list_params = {p["name"] for p in schema["paths"]["/events"]["get"]["parameters"]}
    assert {"from", "to", "limit", "cursor"} <= list_params
