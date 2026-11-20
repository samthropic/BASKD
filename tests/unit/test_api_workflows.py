"""HTTP behaviour of ``POST /workflows/meeting-prep``: shapes, validation, failure envelope."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from cloud_storage_api import DocumentStorage
from fastapi.testclient import TestClient
from issue_tracker_contract import ErrorCode, IssueProvider

from baskd.app import create_app
from baskd.settings import Settings
from baskd.workflow.controlled import FailingDocumentStorage, FailingIssueProvider

URL = "/workflows/meeting-prep"


def body(**overrides: Any) -> dict[str, Any]:
    return {
        "title": "Design review: HW3",
        "start": "2026-11-24T10:00:00-05:00",
        "end": "2026-11-24T10:30:00-05:00",
        "agenda": "1. Walk through DESIGN.md",
    } | overrides


def client_with(
    storage: DocumentStorage | None = None, issues: IssueProvider | None = None
) -> TestClient:
    return TestClient(create_app(settings=Settings(_env_file=None), storage=storage, issues=issues))


def request_lines(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == "baskd.requests"]


class TestSuccess:
    def test_returns_201_with_every_record_in_utc(self, client: TestClient) -> None:
        response = client.post(URL, json=body())

        assert response.status_code == 201
        data = response.json()
        event = data["event"]
        assert (event["title"], event["start"], event["end"]) == (
            "Design review: HW3",
            "2026-11-24T15:00:00Z",
            "2026-11-24T15:30:00Z",
        )
        assert data["document"]["path"] == f"/baskd/meeting-prep/{event['id']}.md"
        assert data["document"]["id"]
        assert data["issue"]["title"] == f"Prep: Design review: HW3 [evt:{event['id']}]"
        assert [(s["step"], s["reused"]) for s in data["steps"]] == [
            ("create_event", False),
            ("save_agenda", False),
            ("create_issue", False),
        ]

    def test_the_event_is_a_real_event_of_the_api(self, client: TestClient) -> None:
        event_id = client.post(URL, json=body()).json()["event"]["id"]
        assert client.get(f"/events/{event_id}").json()["title"] == "Design review: HW3"

    def test_resuming_with_event_id_creates_nothing_new(self, client: TestClient) -> None:
        first = client.post(URL, json=body()).json()
        again = client.post(URL, json=body(event_id=first["event"]["id"]))

        assert again.status_code == 201
        assert [s["reused"] for s in again.json()["steps"]] == [True, True, True]
        listed = client.get(
            "/events", params={"from": "2026-11-24T00:00:00Z", "to": "2026-11-25T00:00:00Z"}
        )
        assert len(listed.json()["items"]) == 1

    def test_agenda_is_optional(self, client: TestClient) -> None:
        payload = body()
        del payload["agenda"]
        assert client.post(URL, json=payload).status_code == 201


class TestValidation:
    @pytest.mark.parametrize(
        "payload",
        [
            body(end="2026-11-24T09:00:00-05:00"),
            body(start="2026-11-24T10:00:00"),
            body(title=""),
            body(title="x" * 201),
            body(agenda="x" * 10_001),
            body(event_id=""),
            body(colour="blue"),
        ],
    )
    def test_invalid_body_is_422_before_any_provider_call(
        self, payload: dict[str, Any], caplog: pytest.LogCaptureFixture
    ) -> None:
        client = client_with(storage=FailingDocumentStorage())
        with caplog.at_level(logging.INFO, logger="baskd"):
            response = client.post(URL, json=payload)

        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "invalid_input"
        assert "failed_step" not in error
        assert request_lines(caplog)[-1]["provider_involved"] is False


class TestFailures:
    def test_storage_down_is_503_with_the_step_and_what_exists(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        client = client_with(storage=FailingDocumentStorage())
        with caplog.at_level(logging.INFO, logger="baskd"):
            response = client.post(URL, json=body())

        assert response.status_code == 503
        assert response.headers["Retry-After"] == "5"
        error = response.json()["error"]
        assert error["code"] == "provider_unavailable"
        assert error["retryable"] is True
        assert error["failed_step"] == "save_agenda"
        assert [(c["step"], c["reused"]) for c in error["completed"]] == [("create_event", False)]

        line = request_lines(caplog)[-1]
        assert (line["event"], line["failed_step"], line["error"]) == (
            "request_failed",
            "save_agenda",
            "provider_unavailable",
        )
        assert line["provider_involved"] is True
        event_id = error["completed"][0]["id"]
        assert event_id not in caplog.text
        assert "Design review" not in caplog.text

    def test_uncertain_issue_create_is_502_not_retryable(self) -> None:
        client = client_with(issues=FailingIssueProvider(ErrorCode.INTERNAL_ERROR))
        response = client.post(URL, json=body())

        assert response.status_code == 502
        error = response.json()["error"]
        assert (error["code"], error["retryable"], error["failed_step"]) == (
            "provider_error",
            False,
            "create_issue",
        )
        assert [c["step"] for c in error["completed"]] == ["create_event", "save_agenda"]
        assert "Retry-After" not in response.headers

    def test_access_denied_is_403(self) -> None:
        client = client_with(issues=FailingIssueProvider(ErrorCode.ACCESS_DENIED))
        response = client.post(URL, json=body())
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "access_denied"

    def test_unknown_event_id_is_404_with_nothing_completed(self, client: TestClient) -> None:
        response = client.post(URL, json=body(event_id="no-such-event"))

        assert response.status_code == 404
        error = response.json()["error"]
        assert (error["code"], error["failed_step"], error["completed"]) == (
            "not_found",
            "create_event",
            [],
        )


def test_openapi_documents_the_route_and_its_errors(client: TestClient) -> None:
    operation = client.get("/openapi.json").json()["paths"][URL]["post"]
    assert set(operation["responses"]) >= {"201", "400", "403", "404", "422", "502", "503"}
