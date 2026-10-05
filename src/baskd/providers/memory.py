"""An in-process calendar that honours the :class:`~baskd.ports.CalendarProvider` contract.

It exists so the HTTP layer can be exercised quickly and deterministically, and so
teammates can run the service without provider credentials. It intentionally mirrors the
real provider's observable semantics (overlap-based filtering, start-time ordering,
not-found on deleted events) so tests written against it stay meaningful.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from datetime import datetime
from uuid import uuid4

from baskd.errors import EventNotFound, InvalidRequest
from baskd.models import Event, EventInput, EventPage, ListEventsQuery


class InMemoryCalendarProvider:
    """Stores events in a dict. Safe to share across request threads."""

    name = "memory"

    def __init__(self, events: Iterable[Event] = ()) -> None:
        self._events: dict[str, Event] = {event.id: event for event in events}
        self._lock = threading.Lock()

    def create_event(self, data: EventInput) -> Event:
        event = Event(id=uuid4().hex, **data.model_dump())
        with self._lock:
            self._events[event.id] = event
        return event

    def get_event(self, event_id: str) -> Event:
        with self._lock:
            try:
                return self._events[event_id]
            except KeyError:
                raise EventNotFound(event_id) from None

    def list_events(self, query: ListEventsQuery) -> EventPage:
        offset = _decode_cursor(query.cursor)
        with self._lock:
            ordered = sorted(self._events.values(), key=lambda event: (event.start, event.id))
        matching = [event for event in ordered if _overlaps(event, query.time_min, query.time_max)]
        page = matching[offset : offset + query.limit]
        next_offset = offset + query.limit
        next_cursor = str(next_offset) if next_offset < len(matching) else None
        return EventPage(items=page, next_cursor=next_cursor)

    def replace_event(self, event_id: str, data: EventInput) -> Event:
        with self._lock:
            existing = self._events.get(event_id)
            if existing is None:
                raise EventNotFound(event_id)
            updated = Event(id=existing.id, web_link=existing.web_link, **data.model_dump())
            self._events[event_id] = updated
        return updated

    def delete_event(self, event_id: str) -> None:
        with self._lock:
            if self._events.pop(event_id, None) is None:
                raise EventNotFound(event_id)


def _overlaps(event: Event, time_min: datetime | None, time_max: datetime | None) -> bool:
    """Same semantics as Google Calendar's ``timeMin``/``timeMax``: half-open overlap."""
    if time_min is not None and event.end <= time_min:
        return False
    return time_max is None or event.start < time_max


def _decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        offset = int(cursor)
    except ValueError:
        raise InvalidRequest(f"Invalid cursor {cursor!r}") from None
    if offset < 0:
        raise InvalidRequest(f"Invalid cursor {cursor!r}")
    return offset
