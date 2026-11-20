"""Choosing the HW3 storage and issue-tracker implementations through configuration."""

from __future__ import annotations

import pytest
from cloud_storage_api import DocumentStorage
from fastapi.testclient import TestClient
from issue_tracker_contract import IssueProvider
from pydantic import ValidationError

from baskd.app import create_app
from baskd.settings import DROPBOX_VARIABLES, TRELLO_VARIABLES, Settings
from baskd.workflow.composition import build_issues, build_storage
from baskd.workflow.controlled import (
    FailingDocumentStorage,
    FailingIssueProvider,
    InMemoryDocumentStorage,
    InMemoryIssueProvider,
)

FAKE_DROPBOX = {name: f"test-{name.lower()}" for name in DROPBOX_VARIABLES}
FAKE_TRELLO = {name: f"test-{name.lower()}" for name in TRELLO_VARIABLES}


@pytest.fixture(autouse=True)
def no_provider_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test with none of the other teams' variables set."""
    for name in (*DROPBOX_VARIABLES, *TRELLO_VARIABLES, "DROPBOX_ACCESS_TOKEN"):
        monkeypatch.delenv(name, raising=False)


def set_env(monkeypatch: pytest.MonkeyPatch, values: dict[str, str]) -> None:
    for name, value in values.items():
        monkeypatch.setenv(name, value)


class TestSettings:
    def test_defaults_to_our_in_memory_implementations(self) -> None:
        settings = Settings(_env_file=None)
        assert (settings.workflow_storage, settings.workflow_issues) == ("memory", "memory")

    def test_reads_the_selectors_from_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BASKD_WORKFLOW_STORAGE", "failing")
        monkeypatch.setenv("BASKD_WORKFLOW_ISSUES", "failing")
        settings = Settings(_env_file=None)
        assert (settings.workflow_storage, settings.workflow_issues) == ("failing", "failing")

    @pytest.mark.parametrize("storage", ["team3", "team1"])
    def test_dropbox_implementations_need_all_three_variables(
        self, monkeypatch: pytest.MonkeyPatch, storage: str
    ) -> None:
        monkeypatch.setenv("DROPBOX_APP_KEY", "key")
        monkeypatch.setenv("DROPBOX_APP_SECRET", "  ")  # blank counts as missing
        with pytest.raises(ValidationError) as info:
            Settings(workflow_storage=storage, _env_file=None)
        message = str(info.value)
        assert f"BASKD_WORKFLOW_STORAGE={storage} needs" in message
        assert "DROPBOX_APP_SECRET, DROPBOX_REFRESH_TOKEN" in message
        assert "DROPBOX_APP_KEY," not in message

    def test_trello_needs_its_three_variables(self) -> None:
        with pytest.raises(ValidationError, match="TRELLO_API_KEY, TRELLO_TOKEN, TRELLO_LIST_ID"):
            Settings(workflow_issues="team4", _env_file=None)

    def test_reports_both_verticals_at_once(self) -> None:
        with pytest.raises(ValidationError) as info:
            Settings(workflow_storage="team3", workflow_issues="team4", _env_file=None)
        assert "DROPBOX_APP_KEY" in str(info.value)
        assert "TRELLO_API_KEY" in str(info.value)

    def test_accepts_the_other_teams_when_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        set_env(monkeypatch, FAKE_DROPBOX | FAKE_TRELLO)
        settings = Settings(workflow_storage="team1", workflow_issues="team4", _env_file=None)
        assert (settings.workflow_storage, settings.workflow_issues) == ("team1", "team4")

    def test_rejects_an_unknown_implementation(self) -> None:
        with pytest.raises(ValidationError):
            Settings(workflow_storage="team6", _env_file=None)  # type: ignore[arg-type]


class TestBuild:
    @pytest.mark.parametrize(
        ("choice", "expected"),
        [("memory", InMemoryDocumentStorage), ("failing", FailingDocumentStorage)],
    )
    def test_our_storage(self, choice: str, expected: type[DocumentStorage]) -> None:
        storage = build_storage(Settings(workflow_storage=choice, _env_file=None))
        assert isinstance(storage, expected)

    @pytest.mark.parametrize(
        ("choice", "expected"),
        [("memory", InMemoryIssueProvider), ("failing", FailingIssueProvider)],
    )
    def test_our_issue_trackers(self, choice: str, expected: type[object]) -> None:
        issues = build_issues(Settings(workflow_issues=choice, _env_file=None))
        assert isinstance(issues, expected)
        assert isinstance(issues, IssueProvider)

    def test_team3_is_built_offline_without_sdk_retries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Team 3's package loads a .env when imported; keep a developer's .env out of the test.
        monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
        set_env(monkeypatch, FAKE_DROPBOX)
        storage = build_storage(Settings(workflow_storage="team3", _env_file=None))

        from dropbox_client_impl import DropboxDocumentStorage

        assert isinstance(storage, DropboxDocumentStorage)
        sdk = storage._client.dbx  # type: ignore[attr-defined]
        assert sdk._max_retries_on_error == 0
        assert sdk._max_retries_on_rate_limit == 0

    def test_team1_is_built_offline_without_sdk_retries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        set_env(monkeypatch, FAKE_DROPBOX)
        storage = build_storage(Settings(workflow_storage="team1", _env_file=None))

        from team1_dropbox import Team1DropboxStorage

        assert isinstance(storage, Team1DropboxStorage)
        sdk = storage._backend._client  # type: ignore[attr-defined]
        assert sdk._max_retries_on_error == 0
        assert sdk._max_retries_on_rate_limit == 0

    def test_team4_is_trello(self, monkeypatch: pytest.MonkeyPatch) -> None:
        set_env(monkeypatch, FAKE_TRELLO)
        issues = build_issues(Settings(workflow_issues="team4", _env_file=None))

        from team_4_issue_tracker_trello import TrelloIssueProvider

        assert isinstance(issues, TrelloIssueProvider)
        assert isinstance(issues, IssueProvider)


class TestApp:
    def test_app_builds_what_the_settings_name(self) -> None:
        settings = Settings(workflow_storage="failing", workflow_issues="memory", _env_file=None)
        app = create_app(settings=settings)
        assert isinstance(app.state.storage, FailingDocumentStorage)
        assert isinstance(app.state.issues, InMemoryIssueProvider)
        with TestClient(app) as client:
            body = client.get("/health").json()
        assert (body["workflow_storage"], body["workflow_issues"]) == ("failing", "memory")

    def test_injected_implementations_win_over_settings(self) -> None:
        storage, issues = InMemoryDocumentStorage(), InMemoryIssueProvider()
        app = create_app(settings=Settings(_env_file=None), storage=storage, issues=issues)
        assert app.state.storage is storage
        assert app.state.issues is issues
