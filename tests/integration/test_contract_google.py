"""The shared contract's operations, end to end, against the real Google Calendar.

``TestSharedConformanceOnGoogle`` runs the CRUD checks of
:class:`calendar_contract.conformance.CalendarServiceConformance` through
``ContractCalendarService`` on our real ``GoogleCalendarProvider``. This is the evidence
that create, get, replace and delete work through the tagged shared package against the
real provider, not only against the in-memory fake.

The shared failure checks need a provider that fails on demand, which a real calendar
cannot do safely, so they are skipped here. They run against the Google provider over the
fake SDK in ``tests/unit/test_contract_conformance.py``.

The suite deletes every event it creates (its ``created_ids`` fixture), and each test
works only on the events it created, so concurrent runs do not interfere.

    make test-integration        # or: uv run pytest -m integration
"""

from __future__ import annotations

import pytest
from calendar_contract import CalendarService
from calendar_contract.conformance import CalendarServiceConformance, FailingServiceFactory
from pydantic import ValidationError

from baskd.contract import ContractCalendarService
from baskd.providers.google import GoogleCalendarProvider
from baskd.settings import Settings

pytestmark = pytest.mark.integration


def _configured_settings() -> Settings | None:
    try:
        settings = Settings()  # reads BASKD_* env and .env
    except ValidationError:
        return None
    return settings if settings.provider == "google" else None


@pytest.fixture(scope="module")
def google_service() -> CalendarService:
    settings = _configured_settings()
    if settings is None:
        pytest.skip("BASKD_PROVIDER=google with credentials is not configured")
    return ContractCalendarService(GoogleCalendarProvider.from_settings(settings))


class TestSharedConformanceOnGoogle(CalendarServiceConformance):
    @pytest.fixture
    def service(self, google_service: CalendarService) -> CalendarService:
        return google_service

    @pytest.fixture
    def failing_service(self) -> FailingServiceFactory:
        pytest.skip("provider failures run over the fake SDK in tests/unit")
