"""Fault injection behind the Google adapter (HW2 extra credit). See docs/FAULT_INJECTION.md.

Every operation runs through the shared ``CalendarService`` interface over our real Google
adapter, with a fault injected between the adapter and a stateful fake Google Calendar
(``tests/faults.py``). The guarantees checked under each fault:

1. A failure is always one of the five shared codes, never an unhandled exception.
2. ``retryable`` is true only when the write did not happen, so retrying cannot duplicate it.
3. When the outcome of a create or replace is unknown, the write may really have happened,
   which is why it is reported as not retryable.
4. Latency changes nothing but time: the shared suite passes unchanged.
5. A client that retries only ``retryable`` failures never creates a duplicate.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

import pytest
from calendar_contract import CalendarError, CalendarService, CreateEvent, ErrorCode, ReplaceEvent
from calendar_contract.conformance import CalendarServiceConformance, FailingServiceFactory

from tests.faults import FAULTS, FakeCalendar, Fault, contract_service
from tests.unit.test_contract_conformance import google_failing_with

CREATE = CreateEvent(title="Fault drill", start="2030-01-07T15:00:00Z", end="2030-01-07T15:30:00Z")
REPLACE = ReplaceEvent(title="Moved", start="2030-01-07T16:00:00Z", end="2030-01-07T16:30:00Z")

OK = "ok"
UNAVAILABLE = (ErrorCode.PROVIDER_UNAVAILABLE, True)
UNKNOWN = (ErrorCode.PROVIDER_ERROR, False)
DENIED = (ErrorCode.ACCESS_DENIED, False)

#: The documented outcome of each operation under each fault (DESIGN.md §4).
EXPECTED: dict[str, dict[str, Any]] = {
    "none": {"create": OK, "get": OK, "replace": OK, "delete": OK},
    "latency": {"create": OK, "get": OK, "replace": OK, "delete": OK},
    "token-refresh": dict.fromkeys(("create", "get", "replace", "delete"), UNAVAILABLE),
    "dns": dict.fromkeys(("create", "get", "replace", "delete"), UNAVAILABLE),
    "rate-limit": dict.fromkeys(("create", "get", "replace", "delete"), UNAVAILABLE),
    "revoked-key": dict.fromkeys(("create", "get", "replace", "delete"), DENIED),
    # Replace reads before it writes, so a failed read means nothing was sent.
    "read-timeout": {"create": OK, "get": UNAVAILABLE, "replace": UNAVAILABLE, "delete": OK},
    "write-applied-then-timeout": {"create": UNKNOWN, "get": OK, "replace": UNKNOWN, "delete": OK},
    "write-applied-then-503": {"create": UNKNOWN, "get": OK, "replace": UNKNOWN, "delete": OK},
    # Repeating a delete is safe (a second one is 404), so a lost answer stays retryable.
    "delete-applied-then-reset": {"create": OK, "get": OK, "replace": OK, "delete": UNAVAILABLE},
}


def _prepared(fault: Fault) -> tuple[FakeCalendar, CalendarService, str]:
    """A calendar holding one event, with the fault switched on only after setup."""
    calendar = FakeCalendar()
    service = contract_service(calendar)
    existing = service.create(CREATE).id
    calendar.fault = fault
    return calendar, service, existing


def _operation(name: str, service: CalendarService, existing: str) -> Callable[[], object]:
    return {
        "create": lambda: service.create(CREATE),
        "get": lambda: service.get(existing),
        "replace": lambda: service.replace(existing, REPLACE),
        "delete": lambda: service.delete(existing),
    }[name]


@pytest.mark.parametrize("operation", ["create", "get", "replace", "delete"])
@pytest.mark.parametrize("fault_name", list(EXPECTED))
def test_each_operation_fails_the_documented_way(fault_name: str, operation: str) -> None:
    calendar, service, existing = _prepared(FAULTS[fault_name])
    before = {k: dict(v) for k, v in calendar.resources.items()}

    try:
        _operation(operation, service, existing)()
        outcome: Any = OK
    except CalendarError as error:  # guarantee 1: only shared errors escape
        outcome = (error.code, error.retryable)

    assert outcome == EXPECTED[fault_name][operation]
    changed = calendar.resources != before
    if outcome == UNAVAILABLE and operation in ("create", "replace"):
        # Guarantee 2: a retryable write left nothing behind.
        assert not changed
    if outcome == UNKNOWN:
        # Guarantee 3: the write really may have happened; here it did.
        assert changed


@pytest.mark.parametrize(
    ("fault_name", "events_after"),
    [
        ("token-refresh", 1),  # retryable: the client retries once the fault clears
        ("rate-limit", 1),
        ("write-applied-then-timeout", 1),  # not retryable: the client stops
        ("write-applied-then-503", 1),
    ],
)
def test_retrying_only_retryable_failures_never_duplicates(
    fault_name: str, events_after: int
) -> None:
    # Guarantee 5, as a consumer would see it: one create attempt during the fault, then a
    # retry after it clears, but only when the error said retrying was safe.
    calendar = FakeCalendar(fault=FAULTS[fault_name])
    service = contract_service(calendar)
    try:
        service.create(CREATE)
    except CalendarError as error:
        calendar.fault = FAULTS["none"]
        if error.retryable:
            service.create(CREATE)
    assert len(calendar.live()) == events_after


class TestSharedSuiteUnderLatency(CalendarServiceConformance):
    """Guarantee 4: the shared suite passes unchanged when Google is slow."""

    @pytest.fixture
    def service(self) -> CalendarService:
        return contract_service(FakeCalendar(fault=FAULTS["latency"]))

    @pytest.fixture
    def failing_service(self) -> FailingServiceFactory:
        return google_failing_with


@pytest.mark.skipif(
    "FAULT_INJECTION" not in os.environ, reason="run by scripts/fault_injection_report.py"
)
class TestSharedSuiteUnderInjectedFault(CalendarServiceConformance):
    """The whole shared suite with ``FAULT_INJECTION`` switched on after each fixture's setup.

    Used only by ``scripts/fault_injection_report.py`` to record which shared checks still
    pass under each fault; failures here are findings to report, not CI failures.
    """

    @pytest.fixture
    def calendar(self) -> FakeCalendar:
        return FakeCalendar()

    @pytest.fixture
    def service(self, calendar: FakeCalendar) -> CalendarService:
        return contract_service(calendar)

    @pytest.fixture
    def failing_service(self) -> FailingServiceFactory:
        return google_failing_with

    @pytest.fixture(autouse=True)
    def _inject(self, calendar: FakeCalendar, request: pytest.FixtureRequest) -> None:
        # Setup runs fault-free (a missing id; an existing event for get, replace and delete),
        # so each check's own operation is the one that meets the fault. The create checks
        # create inside the check, under the fault.
        setup = ["missing_id"]
        if not request.node.name.startswith("test_create"):
            setup.append("created")
        for name in setup:
            if name in request.fixturenames:
                request.getfixturevalue(name)
        calendar.fault = FAULTS[os.environ["FAULT_INJECTION"]]
