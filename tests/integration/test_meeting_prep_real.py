"""The HW3 workflow against the real providers: Google Calendar, Dropbox and Trello.

Runs only when the environment configures ``BASKD_PROVIDER=google``, a Dropbox storage
(``BASKD_WORKFLOW_STORAGE=team3`` or ``team1``) and ``BASKD_WORKFLOW_ISSUES=team4``, with
the test accounts' ``DROPBOX_*`` and ``TRELLO_*`` variables exported. Otherwise it skips.
It confirms each record in its own provider, resumes once to show nothing is duplicated,
and deletes everything it made.

    BASKD_WORKFLOW_STORAGE=team1 uv run pytest -m integration \
        tests/integration/test_meeting_prep_real.py
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from baskd.app import create_app
from baskd.settings import Settings

pytestmark = pytest.mark.integration


def _real_settings() -> Settings | None:
    try:
        settings = Settings()
    except ValidationError:
        return None
    real = (
        settings.provider == "google"
        and settings.workflow_storage in ("team3", "team1")
        and settings.workflow_issues == "team4"
    )
    return settings if real else None


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    settings = _real_settings()
    if settings is None:
        pytest.skip("Google, a Dropbox storage and Trello are not all configured")
    with TestClient(create_app(settings=settings)) as test_client:
        yield test_client


@pytest.fixture
def made(client: TestClient) -> Iterator[dict[str, Any]]:
    records: dict[str, Any] = {}
    yield records
    app = client.app
    if "event" in records:
        client.delete(f"/events/{records['event']}")
    if "document" in records:
        app.state.storage.delete(records["document"])  # type: ignore[attr-defined]
    if "issue" in records:
        app.state.issues.delete_issue(records["issue"])  # type: ignore[attr-defined]


def test_meeting_prep_lands_in_all_three_providers(
    client: TestClient, made: dict[str, Any]
) -> None:
    start = (datetime.now(UTC) + timedelta(days=30)).replace(microsecond=0)
    body = {
        "title": f"BASKD HW3 check {uuid4().hex[:8]}",
        "start": start.isoformat(),
        "end": (start + timedelta(minutes=30)).isoformat(),
        "agenda": "Created by tests/integration/test_meeting_prep_real.py",
    }

    response = client.post("/workflows/meeting-prep", json=body)
    assert response.status_code == 201, response.text
    data = response.json()
    made.update(
        event=data["event"]["id"], document=data["document"]["path"], issue=data["issue"]["id"]
    )

    assert client.get(f"/events/{made['event']}").json()["title"] == body["title"]
    app = client.app
    saved = app.state.storage.download(made["document"])  # type: ignore[attr-defined]
    assert body["title"].encode() in saved
    issue = app.state.issues.get_issue(made["issue"], fresh=True)  # type: ignore[attr-defined]
    assert f"[evt:{made['event']}]" in issue.title

    again = client.post("/workflows/meeting-prep", json=body | {"event_id": made["event"]})
    assert again.status_code == 201, again.text
    assert [s["reused"] for s in again.json()["steps"]] == [True, True, True]
