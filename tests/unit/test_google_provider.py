"""Google provider: resource mapping, error translation and request shaping.

No network: the SDK's ``service`` object is replaced with a fake that records the requests
it receives and returns canned resources or raises ``HttpError``. The real round trip is
covered by ``tests/integration``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import httplib2
import pytest
from google.auth.exceptions import RefreshError, TransportError
from googleapiclient.errors import HttpError

from baskd.errors import (
    EventNotFound,
    InvalidRequest,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailable,
)
from baskd.models import ListEventsQuery
from baskd.ports import CalendarProvider
from baskd.providers.google import (
    GoogleCalendarProvider,
    event_from_google,
    merge_into_resource,
    to_google_body,
    to_rfc3339,
    translate_http_error,
)
from tests.conftest import T0, event_input

CALENDAR_ID = "team-test@group.calendar.google.com"

GOOGLE_EVENT: dict[str, Any] = {
    "kind": "calendar#event",
    "etag": '"3456"',
    "id": "abc123def456",
    "status": "confirmed",
    "htmlLink": "https://www.google.com/calendar/event?eid=xyz",
    "created": "2026-10-01T10:00:00.000Z",
    "updated": "2026-10-01T10:00:00.123Z",
    "summary": "Sprint planning",
    "description": "Bring the backlog",
    "location": "Room 101",
    "creator": {"email": "robot@project.iam.gserviceaccount.com"},
    "start": {"dateTime": "2026-10-07T11:00:00-04:00", "timeZone": "America/New_York"},
    "end": {"dateTime": "2026-10-07T11:30:00-04:00", "timeZone": "America/New_York"},
    "iCalUID": "abc123def456@google.com",
    "sequence": 0,
    "reminders": {"useDefault": True},
    "eventType": "default",
}


def http_error(status: int, reason: str | None = None, message: str = "boom") -> HttpError:
    payload: dict[str, Any] = {"error": {"code": status, "message": message}}
    if reason:
        payload["error"]["errors"] = [{"domain": "global", "reason": reason, "message": message}]
    return HttpError(
        resp=httplib2.Response({"status": status}), content=json.dumps(payload).encode()
    )


# -- fakes ------------------------------------------------------------------------------------


class FakeRequest:
    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome
        self.executed_with: dict[str, Any] | None = None

    def execute(self, http: Any = None, num_retries: int = 0) -> Any:
        self.executed_with = {"http": http, "num_retries": num_retries}
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class FakeEvents:
    """Stands in for ``service.events()``; queue outcomes per method with ``enqueue``."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._outcomes: dict[str, list[Any]] = {}
        self.requests: list[FakeRequest] = []

    def enqueue(self, method: str, *outcomes: Any) -> None:
        self._outcomes.setdefault(method, []).extend(outcomes)

    def _request(self, method: str, kwargs: dict[str, Any]) -> FakeRequest:
        self.calls.append((method, kwargs))
        outcomes = self._outcomes.get(method)
        if not outcomes:
            raise AssertionError(f"unexpected call to events().{method}({kwargs})")
        request = FakeRequest(outcomes.pop(0))
        self.requests.append(request)
        return request

    def insert(self, **kwargs: Any) -> FakeRequest:
        return self._request("insert", kwargs)

    def get(self, **kwargs: Any) -> FakeRequest:
        return self._request("get", kwargs)

    def list(self, **kwargs: Any) -> FakeRequest:
        return self._request("list", kwargs)

    def update(self, **kwargs: Any) -> FakeRequest:
        return self._request("update", kwargs)

    def delete(self, **kwargs: Any) -> FakeRequest:
        return self._request("delete", kwargs)


class FakeService:
    def __init__(self, events: FakeEvents) -> None:
        self._events = events

    def events(self) -> FakeEvents:
        return self._events


class FakeCredentials:
    """Never asked to sign anything because the fake request never performs HTTP."""


@pytest.fixture
def events() -> FakeEvents:
    return FakeEvents()


@pytest.fixture
def provider(events: FakeEvents) -> GoogleCalendarProvider:
    return GoogleCalendarProvider(
        FakeCredentials(), CALENDAR_ID, timeout_seconds=3.5, service=FakeService(events)
    )


# -- pure mapping -----------------------------------------------------------------------------


class TestEventFromGoogle:
    def test_maps_timed_event_to_utc(self) -> None:
        event = event_from_google(GOOGLE_EVENT)
        assert event.id == "abc123def456"
        assert event.title == "Sprint planning"
        assert event.start == T0
        assert event.end == T0 + timedelta(minutes=30)
        assert event.start.tzinfo == UTC
        assert event.all_day is False
        assert event.description == "Bring the backlog"
        assert event.location == "Room 101"
        assert event.web_link == GOOGLE_EVENT["htmlLink"]

    def test_maps_all_day_event(self) -> None:
        resource = {"id": "d1", "start": {"date": "2026-10-07"}, "end": {"date": "2026-10-08"}}
        event = event_from_google(resource)
        assert event.all_day is True
        assert event.start == datetime(2026, 10, 7, tzinfo=UTC)
        assert event.end == datetime(2026, 10, 8, tzinfo=UTC)

    def test_tolerates_missing_optional_fields(self) -> None:
        resource = {
            "id": "u1",
            "start": {"dateTime": "2026-10-07T15:00:00Z"},
            "end": {"dateTime": "2026-10-07T16:00:00Z"},
        }
        event = event_from_google(resource)
        assert event.title == ""
        assert event.description is None
        assert event.location is None
        assert event.web_link is None

    def test_naive_datetime_falls_back_to_declared_zone(self) -> None:
        resource = {
            "id": "z1",
            "start": {"dateTime": "2026-10-07T11:00:00", "timeZone": "America/New_York"},
            "end": {"dateTime": "2026-10-07T12:00:00", "timeZone": "Nowhere/Invalid"},
        }
        event = event_from_google(resource)
        assert event.start == T0  # 11:00 New York == 15:00 UTC in October
        assert event.end == datetime(2026, 10, 7, 12, 0, tzinfo=UTC)  # unknown zone -> UTC

    def test_missing_times_is_a_provider_error(self) -> None:
        with pytest.raises(ProviderError):
            event_from_google({"id": "x", "start": {}, "end": {}})


class TestRequestBodies:
    def test_rfc3339_is_utc_with_z(self) -> None:
        eastern = timezone(timedelta(hours=-4))
        assert to_rfc3339(datetime(2026, 10, 7, 11, 0, tzinfo=eastern)) == "2026-10-07T15:00:00Z"
        assert to_rfc3339(T0) == "2026-10-07T15:00:00Z"

    def test_insert_body_omits_absent_optionals(self) -> None:
        body = to_google_body(event_input(title="Standup"))
        assert body == {
            "summary": "Standup",
            "start": {"dateTime": "2026-10-07T15:00:00Z"},
            "end": {"dateTime": "2026-10-07T15:30:00Z"},
        }

    def test_insert_body_includes_present_optionals(self) -> None:
        body = to_google_body(event_input(description="d", location="l"))
        assert body["description"] == "d"
        assert body["location"] == "l"

    def test_merge_preserves_unmanaged_fields_and_clears_omitted_ones(self) -> None:
        merged = merge_into_resource(GOOGLE_EVENT, event_input(title="Moved", location="Lobby"))
        assert merged["summary"] == "Moved"
        assert merged["location"] == "Lobby"
        assert "description" not in merged  # omitted -> cleared
        assert merged["start"] == {"dateTime": "2026-10-07T15:00:00Z"}  # timeZone dropped
        assert merged["reminders"] == {"useDefault": True}  # untouched
        assert merged["id"] == GOOGLE_EVENT["id"]
        assert GOOGLE_EVENT["description"] == "Bring the backlog"  # input not mutated


class TestTranslateHttpError:
    @pytest.mark.parametrize("status", [404, 410])
    def test_gone_with_event_id_is_not_found(self, status: int) -> None:
        error = translate_http_error(http_error(status), event_id="e1")
        assert isinstance(error, EventNotFound)
        assert error.event_id == "e1"

    def test_404_without_event_id_means_calendar_inaccessible(self) -> None:
        error = translate_http_error(http_error(404))
        assert isinstance(error, ProviderAuthError)
        assert "Calendar" in error.message

    def test_400_is_invalid_request_with_google_message(self) -> None:
        error = translate_http_error(
            http_error(400, "invalid", "The specified time range is empty.")
        )
        assert isinstance(error, InvalidRequest)
        assert "time range is empty" in error.message

    def test_401_and_403_are_auth_errors(self) -> None:
        assert isinstance(translate_http_error(http_error(401)), ProviderAuthError)
        assert isinstance(translate_http_error(http_error(403, "forbidden")), ProviderAuthError)

    @pytest.mark.parametrize("reason", ["rateLimitExceeded", "userRateLimitExceeded"])
    def test_403_quota_is_unavailable(self, reason: str) -> None:
        assert isinstance(translate_http_error(http_error(403, reason)), ProviderUnavailable)

    @pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
    def test_transient_statuses_are_unavailable(self, status: int) -> None:
        assert isinstance(translate_http_error(http_error(status)), ProviderUnavailable)

    def test_anything_else_is_provider_error(self) -> None:
        error = translate_http_error(http_error(409, "duplicate"))
        assert isinstance(error, ProviderError)
        assert "409" in error.message

    def test_unparseable_body_still_maps(self) -> None:
        raw = HttpError(resp=httplib2.Response({"status": 500}), content=b"<html>oops</html>")
        error = translate_http_error(raw)
        assert isinstance(error, ProviderUnavailable)
        assert "HTTP 500" in error.message


# -- provider behaviour with the fake SDK -----------------------------------------------------


def test_satisfies_the_provider_protocol(provider: GoogleCalendarProvider) -> None:
    assert isinstance(provider, CalendarProvider)
    assert provider.name == "google"


class TestProviderCalls:
    def test_create_sends_body_and_maps_response(
        self, provider: GoogleCalendarProvider, events: FakeEvents
    ) -> None:
        events.enqueue("insert", GOOGLE_EVENT)
        created = provider.create_event(event_input(title="Sprint planning"))
        method, kwargs = events.calls[0]
        assert method == "insert"
        assert kwargs["calendarId"] == CALENDAR_ID
        assert kwargs["body"]["summary"] == "Sprint planning"
        assert created.id == "abc123def456"

    def test_each_call_uses_a_fresh_authorized_http_with_timeout(
        self, provider: GoogleCalendarProvider, events: FakeEvents
    ) -> None:
        events.enqueue("get", GOOGLE_EVENT, GOOGLE_EVENT)
        provider.get_event("abc123def456")
        provider.get_event("abc123def456")
        first, second = (request.executed_with for request in events.requests)
        assert first is not None and second is not None
        assert first["http"] is not second["http"]
        assert first["http"].http.timeout == 3.5
        assert first["num_retries"] == 0

    def test_get_cancelled_event_is_not_found(
        self, provider: GoogleCalendarProvider, events: FakeEvents
    ) -> None:
        events.enqueue("get", {**GOOGLE_EVENT, "status": "cancelled"})
        with pytest.raises(EventNotFound):
            provider.get_event("abc123def456")

    def test_get_404_is_not_found(
        self, provider: GoogleCalendarProvider, events: FakeEvents
    ) -> None:
        events.enqueue("get", http_error(404))
        with pytest.raises(EventNotFound):
            provider.get_event("nope")

    def test_list_shapes_parameters_and_filters_cancelled(
        self, provider: GoogleCalendarProvider, events: FakeEvents
    ) -> None:
        events.enqueue(
            "list",
            {
                "items": [GOOGLE_EVENT, {**GOOGLE_EVENT, "id": "gone", "status": "cancelled"}],
                "nextPageToken": "token-2",
            },
        )
        page = provider.list_events(
            ListEventsQuery(time_min=T0, time_max=T0 + timedelta(days=1), limit=7, cursor="tok")
        )
        _, kwargs = events.calls[0]
        assert kwargs == {
            "calendarId": CALENDAR_ID,
            "maxResults": 7,
            "singleEvents": True,
            "orderBy": "startTime",
            "showDeleted": False,
            "timeMin": "2026-10-07T15:00:00Z",
            "timeMax": "2026-10-08T15:00:00Z",
            "pageToken": "tok",
        }
        assert [event.id for event in page.items] == ["abc123def456"]
        assert page.next_cursor == "token-2"

    def test_list_without_window_omits_bounds(
        self, provider: GoogleCalendarProvider, events: FakeEvents
    ) -> None:
        events.enqueue("list", {"items": []})
        page = provider.list_events(ListEventsQuery())
        _, kwargs = events.calls[0]
        assert "timeMin" not in kwargs and "timeMax" not in kwargs and "pageToken" not in kwargs
        assert page.items == [] and page.next_cursor is None

    def test_list_bad_page_token_is_invalid_request(
        self, provider: GoogleCalendarProvider, events: FakeEvents
    ) -> None:
        events.enqueue("list", http_error(400, "invalid", "Invalid page token"))
        with pytest.raises(InvalidRequest):
            provider.list_events(ListEventsQuery(cursor="garbage"))

    def test_replace_fetches_then_updates_full_resource(
        self, provider: GoogleCalendarProvider, events: FakeEvents
    ) -> None:
        events.enqueue("get", GOOGLE_EVENT)
        events.enqueue("update", {**GOOGLE_EVENT, "summary": "Moved"})
        replaced = provider.replace_event("abc123def456", event_input(title="Moved"))
        assert [method for method, _ in events.calls] == ["get", "update"]
        _, update_kwargs = events.calls[1]
        assert update_kwargs["eventId"] == "abc123def456"
        assert update_kwargs["body"]["summary"] == "Moved"
        assert update_kwargs["body"]["reminders"] == {"useDefault": True}
        assert replaced.title == "Moved"

    def test_replace_cancelled_event_is_not_found_without_updating(
        self, provider: GoogleCalendarProvider, events: FakeEvents
    ) -> None:
        events.enqueue("get", {**GOOGLE_EVENT, "status": "cancelled"})
        with pytest.raises(EventNotFound):
            provider.replace_event("abc123def456", event_input())
        assert [method for method, _ in events.calls] == ["get"]

    def test_delete_success_and_already_deleted(
        self, provider: GoogleCalendarProvider, events: FakeEvents
    ) -> None:
        events.enqueue("delete", "", http_error(410))
        provider.delete_event("abc123def456")
        with pytest.raises(EventNotFound):
            provider.delete_event("abc123def456")

    def test_create_against_inaccessible_calendar_is_auth_error(
        self, provider: GoogleCalendarProvider, events: FakeEvents
    ) -> None:
        events.enqueue("insert", http_error(404))
        with pytest.raises(ProviderAuthError):
            provider.create_event(event_input())

    @pytest.mark.parametrize(
        ("raised", "expected"),
        [
            (RefreshError("invalid_grant"), ProviderAuthError),
            (TransportError("dns"), ProviderUnavailable),
            (httplib2.ServerNotFoundError("Unable to find the server"), ProviderUnavailable),
            (TimeoutError("timed out"), ProviderUnavailable),
            (ConnectionResetError(), ProviderUnavailable),
        ],
    )
    def test_transport_and_credential_failures(
        self,
        provider: GoogleCalendarProvider,
        events: FakeEvents,
        raised: Exception,
        expected: type[Exception],
    ) -> None:
        events.enqueue("list", raised)
        with pytest.raises(expected):
            provider.list_events(ListEventsQuery())
