"""Fixtures and helpers shared by unit and integration tests."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from baskd.app import create_app
from baskd.models import Event, EventInput, EventPage, ListEventsQuery
from baskd.providers.memory import InMemoryCalendarProvider
from baskd.settings import Settings

T0 = datetime(2026, 10, 7, 15, 0, tzinfo=UTC)


@pytest.fixture
def memory_settings() -> Settings:
    return Settings(provider="memory", _env_file=None)


@pytest.fixture
def memory_provider() -> InMemoryCalendarProvider:
    return InMemoryCalendarProvider()


@pytest.fixture
def app(memory_settings: Settings, memory_provider: InMemoryCalendarProvider) -> FastAPI:
    return create_app(settings=memory_settings, provider=memory_provider)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def event_payload(**overrides: Any) -> dict[str, Any]:
    """A valid ``POST /events`` body; override any field."""
    payload: dict[str, Any] = {
        "title": "Sprint planning",
        "start": "2026-10-07T15:00:00Z",
        "end": "2026-10-07T15:30:00Z",
        "description": "Bring the backlog",
        "location": "Room 101",
    }
    payload.update(overrides)
    return payload


def event_input(
    offset_minutes: int = 0, duration_minutes: int = 30, **overrides: Any
) -> EventInput:
    start = T0 + timedelta(minutes=offset_minutes)
    data: dict[str, Any] = {
        "title": f"Event +{offset_minutes}m",
        "start": start,
        "end": start + timedelta(minutes=duration_minutes),
    }
    data.update(overrides)
    return EventInput(**data)


class FailingProvider:
    """A provider whose every operation raises ``error``; for exercising error mapping."""

    name = "failing"

    def __init__(self, error: Exception) -> None:
        self.error = error

    def create_event(self, data: EventInput) -> Event:
        raise self.error

    def get_event(self, event_id: str) -> Event:
        raise self.error

    def list_events(self, query: ListEventsQuery) -> EventPage:
        raise self.error

    def replace_event(self, event_id: str, data: EventInput) -> Event:
        raise self.error

    def delete_event(self, event_id: str) -> None:
        raise self.error


def failing_client(error: Exception) -> TestClient:
    settings = Settings(provider="memory", _env_file=None)
    app = create_app(settings=settings, provider=FailingProvider(error))
    # Unhandled (non-CalendarError) exceptions would otherwise be re-raised into the test
    # instead of exercising the 500 envelope.
    return TestClient(app, raise_server_exceptions=False)
