"""The in-memory provider must honour the CalendarProvider contract exactly."""

from __future__ import annotations

from datetime import timedelta

import pytest

from baskd.errors import EventNotFound, InvalidRequest
from baskd.models import Event, ListEventsQuery
from baskd.ports import CalendarProvider
from baskd.providers.memory import InMemoryCalendarProvider
from tests.conftest import T0, event_input


def test_satisfies_the_provider_protocol() -> None:
    assert isinstance(InMemoryCalendarProvider(), CalendarProvider)
    assert InMemoryCalendarProvider().name == "memory"


class TestCreateAndGet:
    def test_create_assigns_unique_ids_and_round_trips(
        self, memory_provider: InMemoryCalendarProvider
    ) -> None:
        first = memory_provider.create_event(event_input(description="a"))
        second = memory_provider.create_event(event_input(description="b"))
        assert first.id != second.id
        assert memory_provider.get_event(first.id) == first
        assert first.description == "a"
        assert first.web_link is None

    def test_get_unknown_raises(self, memory_provider: InMemoryCalendarProvider) -> None:
        with pytest.raises(EventNotFound) as info:
            memory_provider.get_event("missing")
        assert info.value.event_id == "missing"
        assert info.value.code == "event_not_found"


class TestReplace:
    def test_replace_keeps_id_and_clears_omitted_optionals(
        self, memory_provider: InMemoryCalendarProvider
    ) -> None:
        created = memory_provider.create_event(event_input(description="old", location="here"))
        replaced = memory_provider.replace_event(created.id, event_input(title="New title"))
        assert replaced.id == created.id
        assert replaced.title == "New title"
        assert replaced.description is None
        assert replaced.location is None
        assert memory_provider.get_event(created.id) == replaced

    def test_replace_all_day_event_is_refused_and_unchanged(self) -> None:
        all_day = Event(
            id="holiday", title="Holiday", start=T0, end=T0 + timedelta(days=1), all_day=True
        )
        provider = InMemoryCalendarProvider([all_day])
        with pytest.raises(InvalidRequest, match="All-day"):
            provider.replace_event("holiday", event_input())
        assert provider.get_event("holiday") == all_day

    def test_replace_unknown_raises(self, memory_provider: InMemoryCalendarProvider) -> None:
        with pytest.raises(EventNotFound):
            memory_provider.replace_event("missing", event_input())


class TestDelete:
    def test_delete_then_get_and_delete_again_raise(
        self, memory_provider: InMemoryCalendarProvider
    ) -> None:
        created = memory_provider.create_event(event_input())
        memory_provider.delete_event(created.id)
        with pytest.raises(EventNotFound):
            memory_provider.get_event(created.id)
        with pytest.raises(EventNotFound):
            memory_provider.delete_event(created.id)


class TestList:
    @pytest.fixture
    def provider(self) -> InMemoryCalendarProvider:
        provider = InMemoryCalendarProvider()
        # Three back-to-back 30 minute events starting at T0, inserted out of order.
        for offset in (60, 0, 30):
            provider.create_event(event_input(offset_minutes=offset))
        return provider

    def test_lists_everything_ordered_by_start(self, provider: InMemoryCalendarProvider) -> None:
        page = provider.list_events(ListEventsQuery())
        assert [event.title for event in page.items] == ["Event +0m", "Event +30m", "Event +60m"]
        assert page.next_cursor is None

    def test_window_uses_overlap_semantics(self, provider: InMemoryCalendarProvider) -> None:
        # [T0+15m, T0+45m) overlaps the first two events but not the third.
        page = provider.list_events(
            ListEventsQuery(
                time_min=T0 + timedelta(minutes=15), time_max=T0 + timedelta(minutes=45)
            )
        )
        assert [event.title for event in page.items] == ["Event +0m", "Event +30m"]

    def test_window_bounds_are_half_open(self, provider: InMemoryCalendarProvider) -> None:
        # An event ending exactly at `from` or starting exactly at `to` is excluded.
        page = provider.list_events(
            ListEventsQuery(
                time_min=T0 + timedelta(minutes=30), time_max=T0 + timedelta(minutes=60)
            )
        )
        assert [event.title for event in page.items] == ["Event +30m"]

    def test_open_ended_windows(self, provider: InMemoryCalendarProvider) -> None:
        only_from = provider.list_events(ListEventsQuery(time_min=T0 + timedelta(minutes=45)))
        assert [e.title for e in only_from.items] == ["Event +30m", "Event +60m"]
        only_to = provider.list_events(ListEventsQuery(time_max=T0 + timedelta(minutes=1)))
        assert [e.title for e in only_to.items] == ["Event +0m"]

    def test_pagination_walks_every_item_exactly_once(
        self, provider: InMemoryCalendarProvider
    ) -> None:
        seen: list[str] = []
        cursor: str | None = None
        pages = 0
        while True:
            page = provider.list_events(ListEventsQuery(limit=2, cursor=cursor))
            pages += 1
            seen.extend(event.title for event in page.items)
            cursor = page.next_cursor
            if cursor is None:
                break
        assert pages == 2
        assert seen == ["Event +0m", "Event +30m", "Event +60m"]

    def test_empty_calendar(self, memory_provider: InMemoryCalendarProvider) -> None:
        page = memory_provider.list_events(ListEventsQuery())
        assert page.items == []
        assert page.next_cursor is None

    @pytest.mark.parametrize("cursor", ["not-a-number", "-1", "1.5"])
    def test_malformed_cursor_is_rejected(
        self, provider: InMemoryCalendarProvider, cursor: str
    ) -> None:
        with pytest.raises(InvalidRequest):
            provider.list_events(ListEventsQuery(cursor=cursor))
