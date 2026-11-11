"""BASK'D behind the shared Calendar contract of Teams 2, 5 and 7.

The three Calendar teams publish their joint contract as the ``calendar-contract``
package. Its :class:`calendar_contract.CalendarService` protocol has the four shared
operations (create, get, replace, delete). They work on the shared models and raise
:class:`calendar_contract.CalendarError` with one of five shared codes.
:class:`ContractCalendarService` provides that protocol on top of any
:class:`~baskd.ports.CalendarProvider`, which is how the package's conformance suite runs
against our providers (``tests/unit/test_contract_conformance.py``).

The HTTP API does not go through this adapter. Our own models carry extensions
(``description``, ``location``, ``all_day``, ``web_link``) that the shared models forbid,
so ``api/`` keeps validating with :class:`~baskd.models.EventInput`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from calendar_contract import CalendarError as SharedError
from calendar_contract import CalendarService, CreateEvent, ErrorCode, ReplaceEvent
from calendar_contract import Event as SharedEvent
from pydantic import ValidationError

from baskd import errors
from baskd.models import Event, EventInput
from baskd.ports import CalendarProvider

#: Shared code for each of our error classes. Subclasses inherit their parent's code, and
#: anything else (a bare ``CalendarError``) is reported as ``provider_error``.
SHARED_CODES: dict[type[errors.CalendarError], ErrorCode] = {
    errors.InvalidRequest: ErrorCode.INVALID_INPUT,
    errors.EventNotFound: ErrorCode.NOT_FOUND,
    errors.ProviderAuthError: ErrorCode.ACCESS_DENIED,
    errors.ProviderError: ErrorCode.PROVIDER_ERROR,
    errors.ProviderUnavailable: ErrorCode.PROVIDER_UNAVAILABLE,
}

_UNREPRESENTABLE = "The calendar provider returned an event the shared contract cannot represent"


class ContractCalendarService(CalendarService):
    """A :class:`calendar_contract.CalendarService` backed by a BASK'D provider.

    Inheriting from the protocol is optional, but it makes ``mypy --strict`` check each
    method against the shared signatures. A new package tag that changes them then fails
    type checking here, before any test runs.

    Requests the shared models accept can still break one of our own rules: a title
    longer than 1024 characters, or a range that is empty once sub-seconds are dropped
    (contract rule 14). Those raise ``invalid_input`` before the provider is called. An
    event the shared :class:`calendar_contract.Event` rejects, such as a zero-length
    event created outside this API, raises ``provider_error``.
    """

    def __init__(self, provider: CalendarProvider) -> None:
        self._provider = provider

    def create(self, request: CreateEvent) -> SharedEvent:
        data = _to_input(request)
        with _shared_errors():
            event = self._provider.create_event(data)
        return _to_shared(event)

    def get(self, event_id: str) -> SharedEvent:
        with _shared_errors():
            event = self._provider.get_event(event_id)
        return _to_shared(event)

    def replace(self, event_id: str, request: ReplaceEvent) -> SharedEvent:
        data = _to_input(request)
        with _shared_errors():
            event = self._provider.replace_event(event_id, data)
        return _to_shared(event)

    def delete(self, event_id: str) -> None:
        with _shared_errors():
            self._provider.delete_event(event_id)


def to_shared_error(error: errors.CalendarError) -> SharedError:
    """Translate one of our errors into the shared error, keeping message and retryability."""
    code = next(
        (shared for cls, shared in SHARED_CODES.items() if isinstance(error, cls)),
        ErrorCode.PROVIDER_ERROR,
    )
    return SharedError(code, error.message, error.retryable)


@contextmanager
def _shared_errors() -> Iterator[None]:
    try:
        yield
    except errors.CalendarError as error:
        raise to_shared_error(error) from error


def _to_input(request: CreateEvent | ReplaceEvent) -> EventInput:
    try:
        # The same validation an HTTP body gets: the shared request holds strings.
        return EventInput.model_validate(
            {"title": request.title, "start": request.start, "end": request.end}
        )
    except ValidationError as error:
        problems = [
            {"field": ".".join(str(part) for part in issue["loc"]), "message": issue["msg"]}
            for issue in error.errors(include_url=False, include_input=False)
        ]
        raise SharedError(
            ErrorCode.INVALID_INPUT,
            "The event breaks one of this service's rules",
            retryable=False,
            details={"errors": problems},
        ) from error


def _to_shared(event: Event) -> SharedEvent:
    try:
        return SharedEvent(
            id=event.id, title=event.title, start=_rfc3339(event.start), end=_rfc3339(event.end)
        )
    except ValidationError as error:
        raise SharedError(ErrorCode.PROVIDER_ERROR, _UNREPRESENTABLE, retryable=False) from error


def _rfc3339(value: datetime) -> str:
    """Write an instant in UTC with ``Z``, as the HTTP API does."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
