"""BASK'D against the shared conformance suite of the ``calendar-contract`` package.

``TestSharedConformance`` inherits every check in
:class:`calendar_contract.conformance.CalendarServiceConformance`:

* create, get, replace and delete run on the in-memory provider;
* the shared failures run on the real Google provider over the fake SDK from
  ``test_google_provider.py``, so they exercise our own ``translate_http_error`` and
  ``_execute`` rather than a stub that raises the expected error.

``TestContractCalendarService`` covers what the shared suite cannot know about: our own
limits, and provider events the shared model cannot represent.
"""

from __future__ import annotations

from typing import Any

import pytest
from calendar_contract import CalendarError as SharedError
from calendar_contract import CalendarService, CreateEvent, ErrorCode, ReplaceEvent
from calendar_contract.conformance import (
    WRITE_OPERATIONS,
    CalendarServiceConformance,
    FailingServiceFactory,
    ProviderFailure,
)

from baskd import errors
from baskd.contract import ContractCalendarService, to_shared_error
from baskd.providers.google import GoogleCalendarProvider
from baskd.providers.memory import InMemoryCalendarProvider
from tests.conftest import FailingProvider
from tests.unit.test_google_provider import (
    CALENDAR_ID,
    GOOGLE_EVENT,
    FakeCredentials,
    FakeEvents,
    FakeService,
    http_error,
)

#: What the fake Google SDK raises for each shared failure, on every SDK method.
GOOGLE_FAILURES: dict[ProviderFailure, BaseException] = {
    ProviderFailure.ACCESS_DENIED: http_error(403, "forbidden"),
    ProviderFailure.UNEXPECTED_RESPONSE: http_error(409),
    ProviderFailure.UNAVAILABLE: http_error(503),
}


def google_service(events: FakeEvents) -> ContractCalendarService:
    """Our Google provider on the fake SDK ``events``, behind the shared interface."""
    provider = GoogleCalendarProvider(
        FakeCredentials(), CALENDAR_ID, timeout_seconds=3.5, service=FakeService(events)
    )
    return ContractCalendarService(provider)


def google_failing_with(failure: ProviderFailure) -> CalendarService:
    """The Google provider on an SDK that fails every call the way ``failure`` describes."""
    events = FakeEvents()
    if failure is ProviderFailure.UNCERTAIN_WRITE:
        # The connection drops after the request was sent, so Google may have written it.
        # Replace reads the event first, and that read succeeds.
        events.enqueue("get", GOOGLE_EVENT)
        events.enqueue("insert", TimeoutError("timed out"))
        events.enqueue("update", TimeoutError("timed out"))
    else:
        for method in ("insert", "get", "update", "delete"):
            events.enqueue(method, GOOGLE_FAILURES[failure])
    return google_service(events)


class TestSharedConformance(CalendarServiceConformance):
    @pytest.fixture
    def service(self) -> CalendarService:
        return ContractCalendarService(InMemoryCalendarProvider())

    @pytest.fixture
    def failing_service(self) -> FailingServiceFactory:
        return google_failing_with

    @pytest.mark.xfail(
        strict=True,
        reason="#35: a create or replace that times out is still a retryable 503",
    )
    @pytest.mark.parametrize("operation", WRITE_OPERATIONS)
    def test_uncertain_write_raises_non_retryable_provider_error(
        self, failing_service: FailingServiceFactory, operation: str
    ) -> None:
        super().test_uncertain_write_raises_non_retryable_provider_error(failing_service, operation)


def create_request(**overrides: Any) -> CreateEvent:
    fields: dict[str, Any] = {
        "title": "Sync",
        "start": "2030-01-07T16:00:00+01:00",
        "end": "2030-01-07T16:30:00+01:00",
    }
    fields.update(overrides)
    return CreateEvent(**fields)


class TestContractCalendarService:
    @pytest.mark.parametrize(
        ("error", "code", "retryable"),
        [
            (errors.InvalidRequest(), ErrorCode.INVALID_INPUT, False),
            (errors.EventNotFound("e1"), ErrorCode.NOT_FOUND, False),
            (errors.ProviderAuthError(), ErrorCode.ACCESS_DENIED, False),
            (errors.ProviderError(), ErrorCode.PROVIDER_ERROR, False),
            (errors.ProviderUnavailable(), ErrorCode.PROVIDER_UNAVAILABLE, True),
            # A class without its own shared code, such as the base class.
            (errors.CalendarError(), ErrorCode.PROVIDER_ERROR, False),
        ],
    )
    def test_each_error_keeps_its_message_and_retryability(
        self, error: errors.CalendarError, code: ErrorCode, retryable: bool
    ) -> None:
        shared = to_shared_error(error)
        assert (shared.code, shared.message, shared.retryable) == (code, error.message, retryable)

    def test_provider_errors_are_raised_as_shared_errors(self) -> None:
        service = ContractCalendarService(FailingProvider(errors.ProviderUnavailable()))
        with pytest.raises(SharedError) as raised:
            service.get("e1")
        assert raised.value.code is ErrorCode.PROVIDER_UNAVAILABLE
        assert isinstance(raised.value.__cause__, errors.ProviderUnavailable)

    def test_times_are_returned_in_utc_with_z(self) -> None:
        event = ContractCalendarService(InMemoryCalendarProvider()).create(create_request())
        assert (event.start, event.end) == ("2030-01-07T15:00:00Z", "2030-01-07T15:30:00Z")

    def test_title_over_our_limit_is_invalid_input_without_calling_the_provider(self) -> None:
        events = FakeEvents()  # any SDK call fails the test
        with pytest.raises(SharedError) as raised:
            google_service(events).create(create_request(title="x" * 1025))
        assert raised.value.code is ErrorCode.INVALID_INPUT
        assert raised.value.retryable is False
        assert raised.value.details == {
            "errors": [{"field": "title", "message": "String should have at most 1024 characters"}]
        }
        assert events.calls == []

    def test_range_empty_once_sub_seconds_are_dropped_is_invalid_input(self) -> None:
        # Contract rule 14: we drop sub-seconds, then check that end is after start.
        request = ReplaceEvent(
            title="Sync", start="2030-01-07T10:00:00.1Z", end="2030-01-07T10:00:00.9Z"
        )
        service = ContractCalendarService(InMemoryCalendarProvider())
        with pytest.raises(SharedError) as raised:
            service.replace("e1", request)
        assert raised.value.code is ErrorCode.INVALID_INPUT

    def test_replacing_an_all_day_event_is_invalid_input(self) -> None:
        events = FakeEvents()
        all_day = {**GOOGLE_EVENT, "start": {"date": "2026-11-26"}, "end": {"date": "2026-11-27"}}
        events.enqueue("get", all_day)
        request = ReplaceEvent(**create_request().model_dump())
        with pytest.raises(SharedError) as raised:
            google_service(events).replace(GOOGLE_EVENT["id"], request)
        assert raised.value.code is ErrorCode.INVALID_INPUT
        assert raised.value.message == errors.ALL_DAY_NOT_REPLACEABLE
        assert [method for method, _ in events.calls] == ["get"]

    def test_untitled_provider_event_is_read_with_an_empty_title(self) -> None:
        # Contract rule 13: a server never invents a title.
        events = FakeEvents()
        events.enqueue("get", {k: v for k, v in GOOGLE_EVENT.items() if k != "summary"})
        assert google_service(events).get(GOOGLE_EVENT["id"]).title == ""

    def test_zero_length_provider_event_is_provider_error(self) -> None:
        # Google stores events whose end equals their start; the shared Event rejects them.
        events = FakeEvents()
        events.enqueue("get", {**GOOGLE_EVENT, "end": GOOGLE_EVENT["start"]})
        with pytest.raises(SharedError) as raised:
            google_service(events).get(GOOGLE_EVENT["id"])
        assert raised.value.code is ErrorCode.PROVIDER_ERROR
        assert raised.value.retryable is False
