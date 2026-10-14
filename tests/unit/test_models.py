"""Boundary validation: what the API accepts and rejects, independent of any provider."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from baskd.models import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    Event,
    EventInput,
    ListEventsQuery,
)
from tests.conftest import T0


class TestEventInput:
    def test_accepts_minimal_valid_input(self) -> None:
        event = EventInput(title="Standup", start=T0, end=T0 + timedelta(minutes=15))
        assert event.description is None
        assert event.location is None

    def test_rejects_naive_datetimes(self) -> None:
        with pytest.raises(ValidationError, match="timezone"):
            EventInput(title="x", start=datetime(2026, 10, 7, 15), end=T0 + timedelta(hours=1))

    @pytest.mark.parametrize("delta", [timedelta(0), timedelta(minutes=-1)])
    def test_rejects_end_not_after_start(self, delta: timedelta) -> None:
        with pytest.raises(ValidationError, match="end must be after start"):
            EventInput(title="x", start=T0, end=T0 + delta)

    @pytest.mark.parametrize("title", ["", "   ", "\t\n"])
    def test_rejects_blank_title(self, title: str) -> None:
        with pytest.raises(ValidationError):
            EventInput(title=title, start=T0, end=T0 + timedelta(hours=1))

    def test_strips_whitespace(self) -> None:
        event = EventInput(title="  Standup  ", start=T0, end=T0 + timedelta(hours=1))
        assert event.title == "Standup"

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs"):
            EventInput.model_validate(
                {"title": "x", "start": T0, "end": T0 + timedelta(hours=1), "attendees": []}
            )

    def test_blank_optional_text_becomes_none(self) -> None:
        event = EventInput(
            title="x", start=T0, end=T0 + timedelta(hours=1), description="", location=" "
        )
        assert event.description is None
        assert event.location is None

    def test_truncates_sub_second_precision(self) -> None:
        start = T0.replace(microsecond=123456)
        event = EventInput(title="x", start=start, end=start + timedelta(hours=1))
        assert event.start.microsecond == 0
        assert event.end.microsecond == 0

    def test_preserves_offset_of_input(self) -> None:
        eastern = timezone(timedelta(hours=-4))
        start = datetime(2026, 10, 7, 11, 0, tzinfo=eastern)
        event = EventInput(title="x", start=start, end=start + timedelta(hours=1))
        assert event.start == T0  # same instant
        assert event.start.utcoffset() == timedelta(hours=-4)  # input shape untouched

    def test_title_length_limit(self) -> None:
        with pytest.raises(ValidationError):
            EventInput(title="x" * 1025, start=T0, end=T0 + timedelta(hours=1))


class TestEvent:
    def test_normalises_times_to_utc(self) -> None:
        eastern = timezone(timedelta(hours=-4))
        event = Event(
            id="e1",
            title="x",
            start=datetime(2026, 10, 7, 11, 0, tzinfo=eastern),
            end=datetime(2026, 10, 7, 12, 0, tzinfo=eastern),
        )
        assert event.start == T0
        assert event.start.tzinfo == UTC
        assert event.end.tzinfo == UTC

    def test_serialises_utc_with_z_suffix(self) -> None:
        event = Event(id="e1", title="x", start=T0, end=T0 + timedelta(hours=1))
        dumped = event.model_dump(mode="json")
        assert dumped["start"] == "2026-10-07T15:00:00Z"
        assert dumped["all_day"] is False
        assert dumped["web_link"] is None

    def test_tolerates_provider_data_the_input_model_would_reject(self) -> None:
        # Real calendars contain untitled events; reading them must not fail.
        event = Event(id="e1", title="", start=T0, end=T0 + timedelta(days=1), all_day=True)
        assert event.title == ""


class TestListEventsQuery:
    def test_defaults(self) -> None:
        query = ListEventsQuery()
        assert query.time_min is None
        assert query.time_max is None
        assert query.limit == DEFAULT_PAGE_SIZE
        assert query.cursor is None

    def test_accepts_api_aliases_and_field_names(self) -> None:
        by_alias = ListEventsQuery.model_validate({"from": T0, "to": T0 + timedelta(days=1)})
        by_name = ListEventsQuery(time_min=T0, time_max=T0 + timedelta(days=1))
        assert by_alias == by_name

    def test_rejects_inverted_window(self) -> None:
        with pytest.raises(ValidationError, match="'to' must be after 'from'"):
            ListEventsQuery(time_min=T0, time_max=T0)

    @pytest.mark.parametrize("limit", [0, MAX_PAGE_SIZE + 1])
    def test_rejects_out_of_range_limit(self, limit: int) -> None:
        with pytest.raises(ValidationError):
            ListEventsQuery(limit=limit)

    def test_rejects_empty_cursor(self) -> None:
        with pytest.raises(ValidationError):
            ListEventsQuery(cursor="")
