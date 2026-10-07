"""The provider interface ("port") the rest of the service depends on.

Any object with these methods is a valid calendar backend; it does not need to inherit
from anything. The HTTP layer receives one through dependency injection
(:mod:`baskd.api.dependencies`), so the same routes serve the real Google Calendar
provider in production and the in-memory fake in tests.

Contract shared by all implementations
--------------------------------------
* Inputs are already validated :class:`~baskd.models.EventInput` /
  :class:`~baskd.models.ListEventsQuery` objects; providers do not re-validate them.
* Returned :class:`~baskd.models.Event` times are in UTC.
* Listing returns events that overlap ``[time_min, time_max)``, ordered by ``start``
  (ties broken deterministically), paginated through an opaque ``cursor`` that is only
  meaningful to the provider that issued it.
* Unknown or deleted event ids raise :class:`~baskd.errors.EventNotFound` for get,
  replace and delete alike. Deleting twice therefore raises on the second call.
* A provider never lets its SDK's exceptions escape; it raises the
  :mod:`baskd.errors` hierarchy instead.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from baskd.models import Event, EventInput, EventPage, ListEventsQuery


@runtime_checkable
class CalendarProvider(Protocol):
    """Operations on a single, pre-configured calendar."""

    @property
    def name(self) -> str:
        """Short identifier reported by ``GET /health`` (e.g. ``"google"``)."""
        ...

    def create_event(self, data: EventInput) -> Event:
        """Create an event and return it with its provider-assigned ``id``."""
        ...

    def get_event(self, event_id: str) -> Event:
        """Return one event or raise :class:`~baskd.errors.EventNotFound`."""
        ...

    def list_events(self, query: ListEventsQuery) -> EventPage:
        """Return a page of events overlapping the query window."""
        ...

    def replace_event(self, event_id: str, data: EventInput) -> Event:
        """Replace every client-editable field of an existing event and return the result.

        Raises :class:`~baskd.errors.InvalidRequest` for an all-day event or a recurring
        series, which :class:`~baskd.models.EventInput` cannot represent, without changing it.
        """
        ...

    def delete_event(self, event_id: str) -> None:
        """Delete an event or raise :class:`~baskd.errors.EventNotFound`."""
        ...
