"""Provider-neutral data model.

Two deliberately separate shapes exist for an event:

* :class:`EventInput` is what clients send. It is strict: unknown fields are rejected,
  times must carry a timezone, and ``end`` must be after ``start``. Validation happens
  here, at the system boundary, and nowhere else.
* :class:`Event` is what the service returns. It is tolerant, because its data comes from
  a provider we do not control (an event in the real calendar may have no title, or be an
  all-day event we cannot create through this API). Its only normalisation is that all
  times are expressed in UTC, so every provider yields identical output for the same
  instant.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

TITLE_MAX_LENGTH = 1024
TEXT_MAX_LENGTH = 8192
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 250


class EventInput(BaseModel):
    """Fields a client supplies to create (``POST``) or replace (``PUT``) an event.

    ``start``/``end`` accept any ISO 8601 timestamp *with* a UTC offset
    (``2026-10-07T15:00:00Z`` or ``2026-10-07T11:00:00-04:00``). Naive timestamps are
    rejected rather than guessed at.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=TITLE_MAX_LENGTH, examples=["Sprint planning"])
    start: AwareDatetime = Field(examples=["2026-10-07T15:00:00Z"])
    end: AwareDatetime = Field(examples=["2026-10-07T15:30:00Z"])
    description: str | None = Field(default=None, max_length=TEXT_MAX_LENGTH)
    location: str | None = Field(default=None, max_length=TITLE_MAX_LENGTH)

    @field_validator("start", "end")
    @classmethod
    def _whole_seconds_only(cls, value: datetime) -> datetime:
        """Providers store whole seconds; truncate up front so every backend agrees."""
        return value.replace(microsecond=0)

    @field_validator("description", "location")
    @classmethod
    def _blank_means_absent(cls, value: str | None) -> str | None:
        """An empty optional text field is the same as an omitted one."""
        return value or None

    @model_validator(mode="after")
    def _end_must_follow_start(self) -> EventInput:
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self


class Event(BaseModel):
    """An event as reported by the service. All times are normalised to UTC."""

    id: str = Field(min_length=1)
    title: str
    start: AwareDatetime
    end: AwareDatetime
    all_day: bool = False
    description: str | None = None
    location: str | None = None
    web_link: str | None = Field(
        default=None,
        description="Link to the event in the provider's own UI, when the provider offers one.",
    )

    @field_validator("start", "end")
    @classmethod
    def _normalise_to_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class ListEventsQuery(BaseModel):
    """Parameters for listing events.

    An event is included when it *overlaps* the half-open window ``[from, to)``, i.e.
    ``event.end > from`` and ``event.start < to``. Either bound may be omitted. Results are
    ordered by start time and paginated with an opaque ``cursor``.
    """

    model_config = ConfigDict(extra="forbid", validate_by_name=True, validate_by_alias=True)

    time_min: AwareDatetime | None = Field(
        default=None,
        alias="from",
        description="Only events ending after this instant.",
        examples=["2026-10-07T00:00:00Z"],
    )
    time_max: AwareDatetime | None = Field(
        default=None,
        alias="to",
        description="Only events starting before this instant.",
        examples=["2026-10-08T00:00:00Z"],
    )
    limit: int = Field(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="Maximum number of events per page.",
    )
    cursor: str | None = Field(
        default=None,
        min_length=1,
        description="Opaque token from a previous page's `next_cursor`.",
    )

    @model_validator(mode="after")
    def _window_must_be_ordered(self) -> ListEventsQuery:
        if (
            self.time_min is not None
            and self.time_max is not None
            and self.time_max <= self.time_min
        ):
            raise ValueError("'to' must be after 'from'")
        return self


class EventPage(BaseModel):
    """One page of a listing. ``next_cursor`` is ``None`` on the last page."""

    items: list[Event]
    next_cursor: str | None = None
