"""HW3 Milestone 1: prepare a meeting across the three verticals, with fixed steps.

1. ``create_event``: create the event on our calendar (``calendar_contract.CalendarService``).
   With ``event_id`` (a resumed run) the event is read instead.
2. ``save_agenda``: save the agenda as ``/baskd/meeting-prep/<event id>.md``
   (``cloud_storage_api.DocumentStorage``). ``create`` never overwrites, so a
   ``ConflictError`` means an earlier attempt already saved it: the step is done.
3. ``create_issue``: look for an issue tagged ``[evt:<event id>]`` among the newest
   ``MAX_LIST_LIMIT`` (``issue_tracker_contract.IssueProvider``); create one only if none.

Nothing is rolled back and nothing is retried here. A failure raises
:class:`WorkflowStepFailed` naming the step and the records already made; the caller resumes
by sending the same request with ``event_id``, and steps 2 and 3 find their earlier work
instead of repeating it. Every failure is translated into our HW1 error model
(:mod:`baskd.errors`).

This module imports only the three shared contracts. Which team's implementation is behind
each one is decided in :mod:`baskd.workflow.composition`.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from calendar_contract import CalendarError as SharedCalendarError
from calendar_contract import CalendarService, CreateEvent
from calendar_contract import ErrorCode as CalendarCode
from calendar_contract import Event as SharedEvent
from cloud_storage_api import (
    ConflictError,
    DocumentStorage,
    FileInfo,
    FileTooLargeError,
    InvalidRequestError,
    PermissionDeniedError,
    ProviderUnavailableError,
    StorageError,
)
from issue_tracker_contract import MAX_LIST_LIMIT, MAX_TITLE_LENGTH, Issue, IssueProvider
from issue_tracker_contract import ErrorCode as IssueCode
from issue_tracker_contract import ServiceError as IssueError
from pydantic import ValidationError

from baskd import errors

logger = logging.getLogger(__name__)

Step = Literal["create_event", "save_agenda", "create_issue"]
AGENDA_FOLDER = "/baskd/meeting-prep"
ISSUE_PREFIX = "Prep: "


@dataclass(frozen=True)
class MeetingPrepRequest:
    title: str
    start: datetime
    end: datetime
    agenda: str = ""
    event_id: str | None = None


@dataclass(frozen=True)
class StepResult:
    """A step that finished: the id of what it made or found, and whether it was found."""

    step: Step
    id: str
    reused: bool


@dataclass(frozen=True)
class MeetingPrepResult:
    event: SharedEvent
    document: FileInfo
    issue: Issue
    steps: list[StepResult]


class WorkflowStepFailed(Exception):
    """A step failed. ``error`` is the HW1 error the caller receives; ``completed`` lists the
    steps that finished before it, so the caller knows what exists and can resume."""

    def __init__(self, step: Step, completed: list[StepResult], error: errors.CalendarError):
        super().__init__(f"{step} failed: {error.code}")
        self.step = step
        self.completed = list(completed)
        self.error = error


class MeetingPrep:
    """The workflow, given one implementation of each contract."""

    def __init__(
        self, calendar: CalendarService, storage: DocumentStorage, issues: IssueProvider
    ) -> None:
        self._calendar = calendar
        self._storage = storage
        self._issues = issues

    def run(self, request: MeetingPrepRequest) -> MeetingPrepResult:
        done: list[StepResult] = []

        event, reused = _step("create_event", done, lambda: self._event(request), request.event_id)
        done.append(StepResult("create_event", event.id, reused))

        path = agenda_path(event.id)
        content = agenda_markdown(event, request.agenda)
        document, reused = _step("save_agenda", done, lambda: self._save(path, content))
        done.append(StepResult("save_agenda", document.path, reused))

        tag = event_tag(event.id)
        issue = _step("create_issue", done, lambda: self._find_issue(tag), reading=True)
        reused = issue is not None
        if issue is None:
            title = issue_title(event.title, tag)
            issue = _step("create_issue", done, lambda: self._issues.create_issue(title))
        done.append(StepResult("create_issue", issue.id, reused))

        return MeetingPrepResult(event=event, document=document, issue=issue, steps=done)

    def _event(self, request: MeetingPrepRequest) -> tuple[SharedEvent, bool]:
        if request.event_id is not None:
            return self._calendar.get(request.event_id), True
        new = CreateEvent(title=request.title, start=_utc(request.start), end=_utc(request.end))
        return self._calendar.create(new), False

    def _save(self, path: str, content: bytes) -> tuple[FileInfo, bool]:
        try:
            return self._storage.create(path, content), False
        except ConflictError:
            return self._storage.get_metadata(path), True

    def _find_issue(self, tag: str) -> Issue | None:
        return next(
            (i for i in self._issues.list_issues(limit=MAX_LIST_LIMIT) if tag in i.title), None
        )


def agenda_path(event_id: str) -> str:
    """Where the agenda of an event lives. Ids are opaque, so keep only path-safe characters."""
    return f"{AGENDA_FOLDER}/{re.sub(r'[^A-Za-z0-9_-]', '_', event_id)}.md"


def agenda_markdown(event: SharedEvent, agenda: str) -> bytes:
    lines = [
        f"# {event.title}",
        "",
        f"- Start: {event.start}",
        f"- End: {event.end}",
        f"- Calendar event: {event.id}",
        "",
        "## Agenda",
        "",
        agenda.strip() or "_No agenda yet._",
        "",
    ]
    return "\n".join(lines).encode()


def event_tag(event_id: str) -> str:
    return f"[evt:{event_id}]"


def issue_title(title: str, tag: str) -> str:
    """``Prep: <title> <tag>``, shortening the title so the whole fits the contract's limit."""
    room = MAX_TITLE_LENGTH - len(ISSUE_PREFIX) - len(tag) - 1
    if len(title) > room:
        title = title[: max(room - 1, 0)] + "…"
    return f"{ISSUE_PREFIX}{title} {tag}"[:MAX_TITLE_LENGTH]


def _step[T](
    step: Step,
    done: list[StepResult],
    action: Callable[[], T],
    event_id: str | None = None,
    *,
    reading: bool = False,
) -> T:
    """Run one step's call, turning any failure into :class:`WorkflowStepFailed`."""
    try:
        return action()
    except SharedCalendarError as error:
        raise WorkflowStepFailed(step, done, _from_calendar(error, event_id)) from error
    except StorageError as error:
        raise WorkflowStepFailed(step, done, _from_storage(error)) from error
    except IssueError as error:
        raise WorkflowStepFailed(step, done, _from_issues(error, reading=reading)) from error
    except ValidationError as error:
        problem = errors.InvalidRequest("The request breaks one of the calendar contract's rules")
        raise WorkflowStepFailed(step, done, problem) from error
    except Exception as error:
        # Another team's package broke its contract (raised something other than its
        # contract's errors). Report the step; log the type only, as messages may hold data.
        logger.warning("workflow step %s raised %s", step, type(error).__name__)
        unexpected = errors.ProviderError(f"The {step} step failed unexpectedly")
        raise WorkflowStepFailed(step, done, unexpected) from error


def _from_calendar(error: SharedCalendarError, event_id: str | None) -> errors.CalendarError:
    if error.code is CalendarCode.NOT_FOUND and event_id is not None:
        return errors.EventNotFound(event_id)
    if error.code is CalendarCode.INVALID_INPUT:
        return errors.InvalidRequest(error.message)
    if error.code is CalendarCode.ACCESS_DENIED:
        return errors.ProviderAuthError(error.message)
    if error.code is CalendarCode.PROVIDER_UNAVAILABLE:
        return errors.ProviderUnavailable(error.message)
    return errors.ProviderError(error.message)


def _from_storage(error: StorageError) -> errors.CalendarError:
    message = f"Storage: {error.message or error.code}"
    if isinstance(error, InvalidRequestError | FileTooLargeError):
        return errors.InvalidRequest(message)
    if isinstance(error, PermissionDeniedError):
        return errors.ProviderAuthError(message)
    if isinstance(error, ProviderUnavailableError):
        # Safe to retry: the agenda's path is fixed, so a save that did land is found.
        return errors.ProviderUnavailable(message)
    return errors.ProviderError(message)


def _from_issues(error: IssueError, *, reading: bool) -> errors.CalendarError:
    message = f"Issue tracker: {error.message}"
    if error.code is IssueCode.ACCESS_DENIED:
        return errors.ProviderAuthError(message)
    if error.code is IssueCode.INVALID_INPUT:
        return errors.InvalidRequest(message)
    if error.code is IssueCode.PROVIDER_ERROR and (reading or not error.may_have_applied):
        # Nothing was written (a failed lookup, or a create that never reached the provider).
        return errors.ProviderUnavailable(message)
    # The issue may exist now. Not retryable as-is; a resumed run finds it by its tag first.
    return errors.ProviderError(message)


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
