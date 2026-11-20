"""The meeting-prep workflow: fixed steps, step-level failures, and resuming without duplicates."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import pytest
from calendar_contract import CalendarError as SharedCalendarError
from calendar_contract import CreateEvent
from calendar_contract import ErrorCode as CalendarCode
from calendar_contract import Event as SharedEvent
from cloud_storage_api import (
    FileTooLargeError,
    InvalidOperationError,
    InvalidRequestError,
    NotFoundError,
    PermissionDeniedError,
    ProviderError,
    StorageError,
)
from issue_tracker_contract import MAX_TITLE_LENGTH, ErrorCode, Issue, ServiceError

from baskd import errors
from baskd.contract import ContractCalendarService
from baskd.models import ListEventsQuery
from baskd.providers.memory import InMemoryCalendarProvider
from baskd.workflow.controlled import (
    FailingDocumentStorage,
    FailingIssueProvider,
    InMemoryDocumentStorage,
    InMemoryIssueProvider,
)
from baskd.workflow.meeting_prep import (
    MeetingPrep,
    MeetingPrepRequest,
    WorkflowStepFailed,
    agenda_markdown,
    agenda_path,
    issue_title,
)

START = datetime(2026, 11, 24, 15, tzinfo=UTC)
END = datetime(2026, 11, 24, 15, 30, tzinfo=UTC)


def request(**overrides: Any) -> MeetingPrepRequest:
    values: dict[str, Any] = {
        "title": "Design review",
        "start": START,
        "end": END,
        "agenda": "1. DESIGN.md",
    }
    return MeetingPrepRequest(**(values | overrides))


class World:
    """One provider of each kind, with a way to count what exists."""

    def __init__(self) -> None:
        self.calendar = InMemoryCalendarProvider()
        self.storage = InMemoryDocumentStorage()
        self.issues = InMemoryIssueProvider()

    def workflow(
        self, storage: Any = None, issues: Any = None, calendar: Any = None
    ) -> MeetingPrep:
        return MeetingPrep(
            calendar or ContractCalendarService(self.calendar),
            storage or self.storage,
            issues or self.issues,
        )

    def counts(self) -> tuple[int, int, int]:
        events = self.calendar.list_events(ListEventsQuery()).items
        files = self.storage.list_files("/baskd/meeting-prep") if self._has_files() else []
        return len(events), len(files), len(self.issues.list_issues(limit=100))

    def _has_files(self) -> bool:
        try:
            self.storage.get_metadata("/baskd/meeting-prep")
        except NotFoundError:
            return False
        return True


@pytest.fixture
def world() -> World:
    return World()


def failure(workflow: MeetingPrep, req: MeetingPrepRequest) -> WorkflowStepFailed:
    with pytest.raises(WorkflowStepFailed) as info:
        workflow.run(req)
    return info.value


class TestSuccess:
    def test_runs_the_three_steps_in_order(self, world: World) -> None:
        result = world.workflow().run(request())

        event = result.event
        assert (event.title, event.start, event.end) == (
            "Design review",
            "2026-11-24T15:00:00Z",
            "2026-11-24T15:30:00Z",
        )
        assert result.document.path == f"/baskd/meeting-prep/{event.id}.md"
        saved = world.storage.download(result.document.path).decode()
        assert "# Design review" in saved
        assert "1. DESIGN.md" in saved
        assert result.issue.title == f"Prep: Design review [evt:{event.id}]"
        assert [(s.step, s.id, s.reused) for s in result.steps] == [
            ("create_event", event.id, False),
            ("save_agenda", result.document.path, False),
            ("create_issue", result.issue.id, False),
        ]
        assert world.counts() == (1, 1, 1)

    def test_resuming_a_finished_run_reuses_everything(self, world: World) -> None:
        first = world.workflow().run(request())
        again = world.workflow().run(request(event_id=first.event.id))

        assert [s.reused for s in again.steps] == [True, True, True]
        assert (again.event, again.issue) == (first.event, first.issue)
        assert again.document.path == first.document.path
        assert world.counts() == (1, 1, 1)

    def test_resumed_run_uses_the_events_own_title(self, world: World) -> None:
        event = ContractCalendarService(world.calendar).create(
            CreateEvent(
                title="Real title", start="2026-11-24T15:00:00Z", end="2026-11-24T16:00:00Z"
            )
        )
        result = world.workflow().run(request(title="ignored", event_id=event.id))
        assert result.issue.title == f"Prep: Real title [evt:{event.id}]"
        assert result.steps[0].reused is True


class TestFailures:
    def test_calendar_failure_has_nothing_completed(self, world: World) -> None:
        calendar = BrokenCalendar(
            SharedCalendarError(CalendarCode.PROVIDER_UNAVAILABLE, "down", True)
        )
        failed = failure(world.workflow(calendar=calendar), request())

        assert failed.step == "create_event"
        assert failed.completed == []
        assert isinstance(failed.error, errors.ProviderUnavailable)
        assert world.counts() == (0, 0, 0)

    def test_storage_failure_reports_the_event_and_resume_finishes(self, world: World) -> None:
        failed = failure(world.workflow(storage=FailingDocumentStorage()), request())

        assert failed.step == "save_agenda"
        assert [(s.step, s.reused) for s in failed.completed] == [("create_event", False)]
        assert isinstance(failed.error, errors.ProviderUnavailable)
        assert failed.error.retryable is True

        event_id = failed.completed[0].id
        resumed = world.workflow().run(request(event_id=event_id))
        assert [s.reused for s in resumed.steps] == [True, False, False]
        assert world.counts() == (1, 1, 1)

    def test_issue_lookup_failure_reports_two_completed_steps(self, world: World) -> None:
        failed = failure(world.workflow(issues=FailingIssueProvider()), request())

        assert failed.step == "create_issue"
        assert [s.step for s in failed.completed] == ["create_event", "save_agenda"]
        assert isinstance(failed.error, errors.ProviderUnavailable)

    def test_uncertain_issue_create_is_not_retryable_and_resume_does_not_duplicate(
        self, world: World
    ) -> None:
        lost = LostResponseIssues(world.issues)
        failed = failure(world.workflow(issues=lost), request())

        assert failed.step == "create_issue"
        assert isinstance(failed.error, errors.ProviderError)
        assert failed.error.retryable is False

        resumed = world.workflow().run(request(event_id=failed.completed[0].id))
        assert [s.reused for s in resumed.steps] == [True, True, True]
        assert world.counts() == (1, 1, 1)

    def test_create_that_never_reached_the_tracker_is_retryable(self, world: World) -> None:
        issues = LostResponseIssues(world.issues, written=False)
        failed = failure(world.workflow(issues=issues), request())
        assert isinstance(failed.error, errors.ProviderUnavailable)
        assert world.counts() == (1, 1, 0)

    def test_unknown_event_id_is_not_found(self, world: World) -> None:
        failed = failure(world.workflow(), request(event_id="missing"))
        assert failed.step == "create_event"
        assert isinstance(failed.error, errors.EventNotFound)

    def test_invalid_event_is_invalid_input(self, world: World) -> None:
        failed = failure(world.workflow(), request(title="x" * 2000))
        assert isinstance(failed.error, errors.InvalidRequest)

    def test_shared_model_rejection_is_invalid_input(self, world: World) -> None:
        failed = failure(world.workflow(), request(title=""))
        assert failed.step == "create_event"
        assert isinstance(failed.error, errors.InvalidRequest)

    def test_another_teams_contract_violation_names_the_step_and_logs_only_the_type(
        self, world: World, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="baskd"):
            failed = failure(
                world.workflow(storage=Raising(RuntimeError("secret /path"))), request()
            )
        assert failed.step == "save_agenda"
        assert isinstance(failed.error, errors.ProviderError)
        assert "save_agenda" in caplog.text
        assert "RuntimeError" in caplog.text
        assert "secret" not in caplog.text


class TestErrorTranslation:
    @pytest.mark.parametrize(
        ("code", "expected"),
        [
            (CalendarCode.INVALID_INPUT, errors.InvalidRequest),
            (CalendarCode.ACCESS_DENIED, errors.ProviderAuthError),
            (CalendarCode.PROVIDER_ERROR, errors.ProviderError),
            (CalendarCode.NOT_FOUND, errors.ProviderError),  # not resuming: not the caller's id
        ],
    )
    def test_calendar(self, world: World, code: CalendarCode, expected: type[Exception]) -> None:
        calendar = BrokenCalendar(SharedCalendarError(code, "no", False))
        assert isinstance(failure(world.workflow(calendar=calendar), request()).error, expected)

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (InvalidRequestError("bad path"), errors.InvalidRequest),
            (FileTooLargeError("big"), errors.InvalidRequest),
            (PermissionDeniedError("no"), errors.ProviderAuthError),
            (NotFoundError("gone"), errors.ProviderError),
            (InvalidOperationError("folder"), errors.ProviderError),
            (ProviderError("odd"), errors.ProviderError),
            (StorageError(), errors.ProviderError),
        ],
    )
    def test_storage(self, world: World, error: StorageError, expected: type[Exception]) -> None:
        failed = failure(world.workflow(storage=Raising(error)), request())
        assert isinstance(failed.error, expected)
        assert failed.error.message.startswith("Storage ")

    @pytest.mark.parametrize(
        ("code", "expected"),
        [
            (ErrorCode.ACCESS_DENIED, errors.ProviderAuthError),
            (ErrorCode.INVALID_INPUT, errors.InvalidRequest),
            (ErrorCode.SERVICE_NOT_CONFIGURED, errors.ProviderError),
            (ErrorCode.INTERNAL_ERROR, errors.ProviderError),
        ],
    )
    def test_issue_tracker(self, world: World, code: ErrorCode, expected: type[Exception]) -> None:
        failed = failure(world.workflow(issues=FailingIssueProvider(code)), request())
        assert isinstance(failed.error, expected)
        assert failed.error.message.startswith("Issue tracker ")


class TestHelpers:
    def test_agenda_path_keeps_only_safe_characters(self) -> None:
        assert agenda_path("abc_123-x") == "/baskd/meeting-prep/abc_123-x.md"
        assert agenda_path("a/b c.d") == "/baskd/meeting-prep/a_b_c_d.md"

    def test_agenda_without_text_says_so(self) -> None:
        event = SharedEvent(
            id="e1", title="T", start="2026-11-24T15:00:00Z", end="2026-11-24T15:30:00Z"
        )
        text = agenda_markdown(event, "   ").decode()
        assert text.splitlines()[0] == "# T"
        assert "- Calendar event: e1" in text
        assert "_No agenda yet._" in text

    def test_issue_title_fits_the_contract_and_keeps_the_tag(self) -> None:
        tag = "[evt:" + "x" * 60 + "]"
        title = issue_title("y" * 200, tag)
        assert len(title) == MAX_TITLE_LENGTH
        assert title.endswith(f"… {tag}")
        assert issue_title("Short", tag) == f"Prep: Short {tag}"


class BrokenCalendar:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def create(self, request: CreateEvent) -> SharedEvent:
        raise self._error

    def get(self, event_id: str) -> SharedEvent:
        raise self._error

    def replace(self, event_id: str, request: Any) -> SharedEvent:  # pragma: no cover
        raise self._error

    def delete(self, event_id: str) -> None:  # pragma: no cover
        raise self._error


class Raising(InMemoryDocumentStorage):
    """Storage whose ``create`` raises ``error``."""

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error

    def create(self, path: str, content: bytes) -> Any:
        raise self._error


class LostResponseIssues:
    """Writes the issue (or not), then fails as if the response never came back."""

    def __init__(self, inner: InMemoryIssueProvider, *, written: bool = True) -> None:
        self._inner = inner
        self._written = written

    def create_issue(self, title: str) -> Issue:
        if self._written:
            self._inner.create_issue(title)
        raise ServiceError(
            ErrorCode.PROVIDER_ERROR,
            "Trello did not answer",
            provider_involved=True,
            may_have_applied=self._written,
        )

    def list_issues(self, *, limit: int) -> list[Issue]:
        return self._inner.list_issues(limit=limit)

    def __getattr__(self, name: str) -> Any:  # pragma: no cover
        return getattr(self._inner, name)


def test_conflict_on_save_means_already_saved(world: World) -> None:
    first = world.workflow().run(request())
    world.storage.replace(first.document.path, b"edited by hand")
    world.issues.delete_issue(first.issue.id)

    again = world.workflow().run(request(event_id=first.event.id, agenda="different"))

    assert [s.reused for s in again.steps] == [True, True, False]
    assert world.storage.download(first.document.path) == b"edited by hand"
