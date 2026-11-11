"""Google Calendar implementation of :class:`~baskd.ports.CalendarProvider`.

Authentication uses a *service account* (a robot identity) that the team's shared test
calendar has been shared with; see ``docs/HUMAN_STEPS.md``. No end-user OAuth flow is
involved, which keeps local setup to "put the key file in ``secrets/``".

Provider facts that shape this module (each is reflected in the public API or docs):

* Google identifies a calendar by an id such as ``abc@group.calendar.google.com``. The
  service is bound to exactly one calendar at startup.
* ``events.get`` on a deleted event may return the event with ``status: "cancelled"``
  rather than a 404, and ``events.delete`` on an already-deleted event returns 410 Gone.
  Both are reported as :class:`~baskd.errors.EventNotFound`.
* All-day events carry a ``date`` instead of a ``dateTime``; they are reported with
  ``all_day=true`` and midnight-UTC bounds but cannot be created or replaced through this
  API. Neither can a recurring *series*; single occurrences can be replaced.
* A service account cannot invite attendees without domain-wide delegation, so the API
  does not expose attendees at all.
* A create or replace that times out, or that Google answers with a 5xx, may still have
  been applied. It is reported as :class:`~baskd.errors.ProviderError` (outcome unknown,
  not retryable) rather than as a temporary outage, so callers do not re-send a write that
  may already have happened. Failures before the request reached Google stay retryable.
* ``googleapiclient``'s HTTP transport is not thread-safe, so every call gets its own
  ``AuthorizedHttp`` with an explicit timeout.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httplib2
from google.auth.exceptions import RefreshError, TransportError
from google.oauth2 import service_account
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from baskd.errors import (
    ALL_DAY_NOT_REPLACEABLE,
    SERIES_NOT_REPLACEABLE,
    CalendarError,
    EventNotFound,
    InvalidRequest,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailable,
)
from baskd.models import Event, EventInput, EventPage, ListEventsQuery
from baskd.settings import Settings

logger = logging.getLogger(__name__)

#: Least-privilege scope: read/write events, no calendar management.
SCOPES = ("https://www.googleapis.com/auth/calendar.events",)

_QUOTA_REASONS = frozenset(
    {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded", "dailyLimitExceeded"}
)
_TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})
_GONE_STATUSES = frozenset({404, 410})
#: 5xx answers to a write do not say whether the write was applied (429 means it was not).
_WRITE_UNKNOWN_STATUSES = frozenset({500, 502, 503, 504})
#: Transport failures that mean the write was not applied: the token refresh failed
#: (``TransportError``; raised before sending, or after Google answered 401) or the DNS
#: lookup failed. A refused connection is not listed: httplib2 reconnects and re-sends once
#: when a connection closes without an answer, so it can follow a request that was sent.
_NOT_SENT_ERRORS = (TransportError, httplib2.ServerNotFoundError)
#: Public message for a write whose outcome is unknown (contract rule 6).
WRITE_OUTCOME_UNKNOWN = (
    "The calendar provider did not confirm the change; it may or may not have been applied. "
    "Read the event or list the window before sending it again"
)


def load_credentials(settings: Settings) -> Any:
    """Build service-account credentials from inline JSON or a key file."""
    if settings.google_credentials_json is not None:
        try:
            info = json.loads(settings.google_credentials_json.get_secret_value())
        except ValueError as exc:
            raise ValueError("BASKD_GOOGLE_CREDENTIALS_JSON is not valid JSON") from exc
        return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)

    path = settings.google_credentials_file
    if path is None:
        raise ValueError("No Google credentials configured")
    if not path.is_file():
        raise FileNotFoundError(f"Google credentials file not found: {path}")
    return service_account.Credentials.from_service_account_file(str(path), scopes=SCOPES)


class GoogleCalendarProvider:
    """Talks to one Google calendar through the official ``googleapiclient`` SDK."""

    name = "google"

    def __init__(
        self,
        credentials: Any,
        calendar_id: str,
        *,
        timeout_seconds: float = 10.0,
        service: Any | None = None,
    ) -> None:
        self._credentials = credentials
        self._calendar_id = calendar_id
        self._timeout_seconds = timeout_seconds
        # ``static_discovery`` uses the API description bundled with the SDK, so building
        # the client is offline and cheap; the first network call happens on first use.
        self._service = (
            service
            if service is not None
            else build(
                "calendar",
                "v3",
                credentials=credentials,
                static_discovery=True,
                cache_discovery=False,
            )
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> GoogleCalendarProvider:
        if not settings.google_calendar_id:
            raise ValueError("BASKD_GOOGLE_CALENDAR_ID is required")
        return cls(
            load_credentials(settings),
            settings.google_calendar_id,
            timeout_seconds=settings.google_timeout_seconds,
        )

    # -- CalendarProvider ---------------------------------------------------------------

    def create_event(self, data: EventInput) -> Event:
        request = self._events().insert(calendarId=self._calendar_id, body=to_google_body(data))
        return event_from_google(self._execute(request, write=True))

    def get_event(self, event_id: str) -> Event:
        return event_from_google(self._fetch_live(event_id))

    def list_events(self, query: ListEventsQuery) -> EventPage:
        params: dict[str, Any] = {
            "calendarId": self._calendar_id,
            "maxResults": query.limit,
            "singleEvents": True,  # expand recurring events into instances ...
            "orderBy": "startTime",  # ... which is what makes ordering by start possible
            "showDeleted": False,
        }
        if query.time_min is not None:
            params["timeMin"] = to_rfc3339(query.time_min)
        if query.time_max is not None:
            params["timeMax"] = to_rfc3339(query.time_max)
        if query.cursor is not None:
            params["pageToken"] = query.cursor
        resource = self._execute(self._events().list(**params))
        items = [
            event_from_google(item)
            for item in resource.get("items", [])
            if item.get("status") != "cancelled"
        ]
        return EventPage(items=items, next_cursor=resource.get("nextPageToken"))

    def replace_event(self, event_id: str, data: EventInput) -> Event:
        # Fetch-modify-update is Google's documented way to edit an event: sending the
        # whole resource back preserves fields this API does not manage (reminders, ...).
        current = self._fetch_live(event_id)
        ensure_replaceable(current)
        request = self._events().update(
            calendarId=self._calendar_id, eventId=event_id, body=merge_into_resource(current, data)
        )
        return event_from_google(self._execute(request, event_id=event_id, write=True))

    def delete_event(self, event_id: str) -> None:
        request = self._events().delete(calendarId=self._calendar_id, eventId=event_id)
        self._execute(request, event_id=event_id)

    # -- internals ----------------------------------------------------------------------

    def _events(self) -> Any:
        return self._service.events()

    def _fetch_live(self, event_id: str) -> dict[str, Any]:
        request = self._events().get(calendarId=self._calendar_id, eventId=event_id)
        resource = self._execute(request, event_id=event_id)
        if resource.get("status") == "cancelled":
            raise EventNotFound(event_id)
        return resource

    def _execute(
        self, request: Any, *, event_id: str | None = None, write: bool = False
    ) -> dict[str, Any]:
        """Run one SDK request, translating every failure into the service's own errors.

        ``write`` marks a create or replace: when such a request may have reached Google
        but got no clear answer, the outcome is unknown and is not reported as retryable.
        A delete is not a write here, because repeating it is safe (a second delete is 404).
        """
        http = AuthorizedHttp(self._credentials, http=httplib2.Http(timeout=self._timeout_seconds))
        try:
            result = request.execute(http=http, num_retries=0)
        except HttpError as exc:
            error = translate_http_error(exc, event_id=event_id, write=write)
            status = _status_of(exc)
            # A missing event is an ordinary outcome; everything else deserves attention.
            logger.log(
                logging.INFO if status in _GONE_STATUSES else logging.WARNING,
                "Google Calendar call failed: http_status=%s reasons=%s -> %s",
                status,
                sorted(_error_reasons(exc)),
                error.code,
            )
            raise error from exc
        except RefreshError as exc:
            # The exception text can quote the token endpoint's response; log only its type.
            logger.error("Google rejected the service-account credentials (%s)", type(exc).__name__)
            raise ProviderAuthError(
                "The calendar provider rejected the service's credentials"
            ) from exc
        except (TransportError, httplib2.HttpLib2Error, OSError) as exc:
            logger.warning("Google Calendar call got no answer: %s", type(exc).__name__)
            if write and not isinstance(exc, _NOT_SENT_ERRORS):
                raise ProviderError(WRITE_OUTCOME_UNKNOWN) from exc
            raise ProviderUnavailable("The calendar provider could not be reached") from exc
        return result if isinstance(result, dict) else {}


# -- translation helpers (pure functions, unit-tested without any network) -----------------


def translate_http_error(
    exc: HttpError, *, event_id: str | None = None, write: bool = False
) -> CalendarError:
    """Map an SDK ``HttpError`` to the provider-neutral error hierarchy.

    ``event_id`` tells us whether a 404 refers to an event (-> not found) or to the
    calendar itself (-> misconfiguration / permissions). Messages are our own: Google's
    error text is not copied into the public contract, and the provider's status and
    ``reason`` codes are only logged (by ``_execute``). ``write`` marks a create or
    replace, for which a 5xx leaves the outcome unknown.
    """
    status = _status_of(exc)
    if status in _GONE_STATUSES:
        if event_id is not None:
            return EventNotFound(event_id)
        return ProviderAuthError("Calendar not found or not shared with the service account")
    if status == 400:
        return InvalidRequest("The calendar provider rejected the request as invalid")
    if status == 401:
        return ProviderAuthError("The calendar provider rejected the service's credentials")
    if status == 403:
        if _error_reasons(exc) & _QUOTA_REASONS:
            return ProviderUnavailable("The calendar provider's quota is exhausted; retry later")
        return ProviderAuthError("The calendar provider denied access to the calendar")
    if write and status in _WRITE_UNKNOWN_STATUSES:
        return ProviderError(WRITE_OUTCOME_UNKNOWN)
    if status in _TRANSIENT_STATUSES:
        return ProviderUnavailable("The calendar provider is temporarily unavailable")
    return ProviderError("The calendar provider returned an unexpected response")


def event_from_google(resource: Mapping[str, Any]) -> Event:
    """Convert a Google ``Event`` resource into the service's :class:`Event`."""
    start, all_day = _parse_edge(resource.get("start") or {})
    end, _ = _parse_edge(resource.get("end") or {})
    return Event(
        id=resource["id"],
        title=resource.get("summary") or "",
        start=start,
        end=end,
        all_day=all_day,
        description=resource.get("description") or None,
        location=resource.get("location") or None,
        web_link=resource.get("htmlLink"),
    )


def to_google_body(data: EventInput) -> dict[str, Any]:
    """The request body for ``events.insert`` built from validated client input."""
    body: dict[str, Any] = {
        "summary": data.title,
        "start": {"dateTime": to_rfc3339(data.start)},
        "end": {"dateTime": to_rfc3339(data.end)},
    }
    if data.description is not None:
        body["description"] = data.description
    if data.location is not None:
        body["location"] = data.location
    return body


def ensure_replaceable(resource: Mapping[str, Any]) -> None:
    """Refuse a replacement this API cannot express faithfully, before calling ``update``.

    * All-day events: :class:`EventInput` only carries instants, so Google would silently
      turn the event into a timed one.
    * Recurring series: Google requires a ``timeZone`` on the bounds of a series, which
      :class:`EventInput` does not carry, so Google would reject the update with a
      confusing "Missing time zone definition". A single occurrence (the ids that
      ``list_events`` returns) is an ordinary event and can be replaced.
    """
    if "date" in (resource.get("start") or {}):
        raise InvalidRequest(ALL_DAY_NOT_REPLACEABLE)
    if resource.get("recurrence"):
        raise InvalidRequest(SERIES_NOT_REPLACEABLE)


def merge_into_resource(resource: Mapping[str, Any], data: EventInput) -> dict[str, Any]:
    """Overlay the client-editable fields onto a fetched resource for ``events.update``.

    Fields the client cleared (``null``) are removed so the provider clears them too.
    """
    body = dict(resource)
    body.update(to_google_body(data))
    for key, value in (("description", data.description), ("location", data.location)):
        if value is None:
            body.pop(key, None)
    return body


def to_rfc3339(value: datetime) -> str:
    """Format as the RFC 3339 UTC string Google expects (``2026-10-07T15:00:00Z``)."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_edge(edge: Mapping[str, Any]) -> tuple[datetime, bool]:
    """Parse a ``start``/``end`` object. Returns ``(instant_in_utc, is_all_day)``."""
    if "dateTime" in edge:
        parsed = datetime.fromisoformat(edge["dateTime"])
        if parsed.tzinfo is None:  # defensive: Google always sends an offset
            parsed = parsed.replace(tzinfo=_zone(edge.get("timeZone")))
        return parsed.astimezone(UTC), False
    if "date" in edge:
        day = date.fromisoformat(edge["date"])
        return datetime.combine(day, time.min, tzinfo=UTC), True
    raise ProviderError("The calendar provider returned an event without a start or end time")


def _zone(name: str | None) -> tzinfo:
    """Resolve Google's IANA ``timeZone`` name for a naive ``dateTime``.

    Zone data comes from the OS or, where the OS has none (Windows), from the ``tzdata``
    package we depend on, so a valid name always resolves. An unknown name falls back to
    UTC with a warning rather than failing the whole request.
    """
    if not name:
        return UTC
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("Unknown time zone %r on a Google event; reading it as UTC", name)
        return UTC


def _status_of(exc: HttpError) -> int:
    try:
        return int(exc.resp.status)
    except (AttributeError, TypeError, ValueError):
        return 0


def _error_reasons(exc: HttpError) -> set[str]:
    """Extract Google's machine-readable ``reason`` codes from an error body.

    Google's human-readable ``message`` is deliberately ignored: it can echo request data,
    so it goes neither into responses nor into logs.
    """
    reasons: set[str] = set()
    try:
        raw = exc.content.decode("utf-8") if isinstance(exc.content, bytes) else exc.content
        payload = json.loads(raw)
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            for item in error.get("errors") or []:
                if isinstance(item, dict) and item.get("reason"):
                    reasons.add(str(item["reason"]))
    except (AttributeError, TypeError, ValueError):
        pass
    return reasons
