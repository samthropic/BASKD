"""Builds the storage and issue-tracker implementations that the configuration names.

This is the only module that imports another team's package, the way
``providers/google.py`` is the only one that imports the Google SDK. Everything else
depends on the shared contracts (``cloud_storage_api.DocumentStorage``,
``issue_tracker_contract.IssueProvider``), so switching teams is a change to
``BASKD_WORKFLOW_STORAGE`` / ``BASKD_WORKFLOW_ISSUES`` and nothing else.

Other teams' packages are imported only when chosen: Team 3's reads ``.env`` and registers
a global client as a side effect of being imported, and none of that should happen when
the service runs on the in-memory implementations.
"""

from __future__ import annotations

from typing import Any

from cloud_storage_api import DocumentStorage
from issue_tracker_contract import IssueProvider

from baskd.settings import Settings
from baskd.workflow.controlled import (
    FailingDocumentStorage,
    FailingIssueProvider,
    InMemoryDocumentStorage,
    InMemoryIssueProvider,
)


def build_storage(settings: Settings) -> DocumentStorage:
    """The Document Storage named by ``settings.workflow_storage``.

    Credentials come from the process environment (``DROPBOX_*``); ``Settings`` has already
    checked they are there. Building makes no network call.
    """
    choice = settings.workflow_storage
    if choice == "memory":
        return InMemoryDocumentStorage()
    if choice == "failing":
        return FailingDocumentStorage()
    if choice == "team3":
        from dropbox_client_impl import DropboxClient, DropboxDocumentStorage, get_dropbox_client

        return DropboxDocumentStorage(
            client=DropboxClient(dbx=_without_retries(get_dropbox_client()))
        )
    if choice == "team1":
        from team1_dropbox import Team1DropboxStorage
        from team1_dropbox.client import create_dropbox_client_from_env

        return Team1DropboxStorage(client=_without_retries(create_dropbox_client_from_env()))
    raise ValueError(f"Unknown storage implementation {choice!r}")  # pragma: no cover


def build_issues(settings: Settings) -> IssueProvider:
    """The issue tracker named by ``settings.workflow_issues``.

    Team 4's Trello provider reads ``TRELLO_*`` on every call; ``Settings`` checks them at
    startup so a missing one is not first noticed by a user's request.
    """
    choice = settings.workflow_issues
    if choice == "memory":
        return InMemoryIssueProvider()
    if choice == "failing":
        return FailingIssueProvider()
    if choice == "team4":
        from team_4_issue_tracker_trello import TrelloIssueProvider

        return TrelloIssueProvider()
    raise ValueError(f"Unknown issue implementation {choice!r}")  # pragma: no cover


def _without_retries(sdk: Any) -> Any:
    """The same Dropbox SDK client with its own retries turned off.

    By default the SDK retries a failed call 4 times and a rate-limited call without limit,
    which hides failures and can repeat an upload whose outcome was unknown. The workflow
    reports a failure with the step it happened in and lets the caller retry.

    ``sdk.clone(max_retries_on_error=0, ...)`` does not work: ``clone`` writes
    ``max_retries_on_error or self._max_retries_on_error``, so a 0 falls back to the old value.
    The SDK (dropbox 12.1.0) has no public setter, hence the two private attributes; the unit
    tests fail if a new SDK version renames them.
    """
    sdk._max_retries_on_error = 0
    sdk._max_retries_on_rate_limit = 0
    return sdk
