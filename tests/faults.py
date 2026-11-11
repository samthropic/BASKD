"""Fault injection behind the Google adapter: a stateful fake Google Calendar plus faults.

:class:`FakeCalendar` stores events the way Google does (ids, ``status: cancelled`` after a
delete, 404 for an unknown id, 410 for a second delete), so the shared conformance suite's
create, get, replace and delete checks can run against our real ``GoogleCalendarProvider``.
:class:`Fault` describes one failure and where it happens:

* ``before``: the request never reaches Google (token refresh, DNS, a 429);
* ``after``: Google applies the request, then the answer is lost (timeout, reset, a 5xx);
* ``latency``: Google answers correctly, but slowly.

``tests/unit/test_fault_injection.py`` asserts the guarantees under each fault;
``scripts/fault_injection_report.py`` runs the shared suite under each and writes the table in
``docs/FAULT_INJECTION.md``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import httplib2
from google.auth.exceptions import RefreshError, TransportError

from baskd.contract import ContractCalendarService
from baskd.providers.google import GoogleCalendarProvider
from tests.unit.test_google_provider import CALENDAR_ID, FakeCredentials, http_error

WRITES = frozenset({"insert", "update"})
READS = frozenset({"get"})
ALL = frozenset({"insert", "get", "update", "delete"})


@dataclass(frozen=True)
class Fault:
    name: str
    description: str
    methods: frozenset[str] = frozenset()
    stage: str = "before"  # "before" | "after"
    error: Callable[[], BaseException] | None = None
    latency_s: float = 0.0


FAULTS: dict[str, Fault] = {
    fault.name: fault
    for fault in [
        Fault("none", "No fault (baseline)"),
        Fault("latency", "Every Google call answers correctly after 50 ms", latency_s=0.05),
        Fault(
            "token-refresh",
            "Token refresh fails on every call; nothing reaches Google",
            ALL,
            "before",
            lambda: TransportError("token refresh failed"),
        ),
        Fault(
            "dns",
            "DNS lookup for Google fails on every call",
            ALL,
            "before",
            lambda: httplib2.ServerNotFoundError("Unable to find the server"),
        ),
        Fault(
            "rate-limit",
            "Google answers 429 rateLimitExceeded without acting",
            ALL,
            "before",
            lambda: http_error(429, "rateLimitExceeded"),
        ),
        Fault(
            "revoked-key",
            "Google refuses the service account's credentials",
            ALL,
            "before",
            lambda: RefreshError("invalid_grant"),
        ),
        Fault(
            "read-timeout",
            "Every events.get times out (writes are fine)",
            READS,
            "before",
            lambda: TimeoutError("timed out"),
        ),
        Fault(
            "write-applied-then-timeout",
            "Google applies each insert/update, then the answer times out",
            WRITES,
            "after",
            lambda: TimeoutError("timed out"),
        ),
        Fault(
            "write-applied-then-503",
            "Google applies each insert/update, then answers 503",
            WRITES,
            "after",
            lambda: http_error(503),
        ),
        Fault(
            "delete-applied-then-reset",
            "Google applies each delete, then the connection resets",
            frozenset({"delete"}),
            "after",
            lambda: ConnectionResetError(),
        ),
    ]
}


class _Request:
    def __init__(self, calendar: FakeCalendar, method: str, run: Callable[[], Any]) -> None:
        self._calendar, self._method, self._run = calendar, method, run
        self.methodId = f"calendar.events.{method}"

    def execute(self, http: Any = None, num_retries: int = 0) -> Any:
        return self._calendar.execute(self._method, self._run)


@dataclass
class FakeCalendar:
    """Stands in for ``service.events()``, with state, and applies the current fault."""

    fault: Fault = field(default_factory=lambda: FAULTS["none"])
    resources: dict[str, dict[str, Any]] = field(default_factory=dict)

    def events(self) -> FakeCalendar:  # FakeCalendar is also the "service"
        return self

    def execute(self, method: str, run: Callable[[], Any]) -> Any:
        fault = self.fault
        if fault.latency_s:
            time.sleep(fault.latency_s)
        hit = method in fault.methods and fault.error is not None
        if hit and fault.stage == "before":
            assert fault.error is not None
            raise fault.error()
        result = run()
        if hit:
            assert fault.error is not None
            raise fault.error()
        return result

    def live(self) -> list[dict[str, Any]]:
        return [r for r in self.resources.values() if r["status"] != "cancelled"]

    # -- the four calls BASK'D makes ---------------------------------------------------------

    def insert(self, calendarId: str, body: dict[str, Any]) -> _Request:
        def run() -> dict[str, Any]:
            event_id = uuid4().hex
            resource = {
                **body,
                "id": event_id,
                "status": "confirmed",
                "htmlLink": f"https://www.google.com/calendar/event?eid={event_id}",
            }
            self.resources[event_id] = resource
            return dict(resource)

        return _Request(self, "insert", run)

    def get(self, calendarId: str, eventId: str) -> _Request:
        def run() -> dict[str, Any]:
            if eventId not in self.resources:
                raise http_error(404, "notFound")
            return dict(self.resources[eventId])

        return _Request(self, "get", run)

    def update(self, calendarId: str, eventId: str, body: dict[str, Any]) -> _Request:
        def run() -> dict[str, Any]:
            if eventId not in self.resources or self.resources[eventId]["status"] == "cancelled":
                raise http_error(404, "notFound")
            self.resources[eventId] = {**body, "id": eventId, "status": "confirmed"}
            return dict(self.resources[eventId])

        return _Request(self, "update", run)

    def delete(self, calendarId: str, eventId: str) -> _Request:
        def run() -> str:
            resource = self.resources.get(eventId)
            if resource is None:
                raise http_error(404, "notFound")
            if resource["status"] == "cancelled":
                raise http_error(410, "deleted")
            resource["status"] = "cancelled"
            return ""

        return _Request(self, "delete", run)


def contract_service(calendar: FakeCalendar) -> ContractCalendarService:
    """Our real Google adapter, behind the shared interface, over the fake calendar."""
    provider = GoogleCalendarProvider(FakeCredentials(), CALENDAR_ID, service=calendar)
    return ContractCalendarService(provider)
