"""``/events``: create, read, list, replace and delete events on the configured calendar.

Handlers are deliberately thin: validation lives in :mod:`baskd.models`, behaviour in
the provider, and error translation in :mod:`baskd.api.errors`. Handlers are plain
``def`` (not ``async``) because providers are synchronous; FastAPI runs them in its
thread pool.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query, Request, Response, status

from baskd.api.dependencies import Provider
from baskd.api.errors import documented_errors
from baskd.models import Event, EventInput, EventPage, ListEventsQuery

router = APIRouter(prefix="/events", tags=["events"])

EventId = Annotated[
    str,
    Path(min_length=1, max_length=1024, description="Provider-assigned event id."),
]

PROVIDER_FAILURES = (
    status.HTTP_502_BAD_GATEWAY,
    status.HTTP_503_SERVICE_UNAVAILABLE,
)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=Event,
    summary="Create an event",
    description=(
        "Create one timed event on the calendar configured for this service. The provider "
        "assigns the event id; response timestamps are UTC, and the `Location` header points "
        "to the new event's `GET /events/{id}` resource. Repeating the request creates "
        "another event."
    ),
    responses={
        status.HTTP_201_CREATED: {
            "description": "Event created.",
            "headers": {
                "Location": {
                    "description": "URL of the newly created event resource.",
                    "schema": {"type": "string", "format": "uri"},
                }
            },
        },
        **documented_errors(
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            *PROVIDER_FAILURES,
        ),
    },
)
def create_event(
    data: EventInput, provider: Provider, request: Request, response: Response
) -> Event:
    event = provider.create_event(data)
    response.headers["Location"] = str(request.url_for("get_event", event_id=event.id))
    return event


@router.get(
    "",
    response_model=EventPage,
    summary="List events overlapping a time window",
    responses=documented_errors(
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        *PROVIDER_FAILURES,
    ),
)
def list_events(query: Annotated[ListEventsQuery, Query()], provider: Provider) -> EventPage:
    return provider.list_events(query)


@router.get(
    "/{event_id}",
    response_model=Event,
    summary="Get one event",
    responses=documented_errors(status.HTTP_404_NOT_FOUND, *PROVIDER_FAILURES),
)
def get_event(event_id: EventId, provider: Provider) -> Event:
    return provider.get_event(event_id)


@router.put(
    "/{event_id}",
    response_model=Event,
    summary="Replace an event",
    description=(
        "Full replacement: every client-editable field is taken from the body. Omitted "
        "optional fields (`description`, `location`) are cleared. The `id` never changes. "
        "All-day events and recurring series cannot be replaced (`400 invalid_request`); "
        "a single occurrence of a recurring event can."
    ),
    responses=documented_errors(
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        *PROVIDER_FAILURES,
    ),
)
def replace_event(event_id: EventId, data: EventInput, provider: Provider) -> Event:
    return provider.replace_event(event_id, data)


@router.delete(
    "/{event_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete an event",
    description="Deleting an event that does not (or no longer) exists returns 404.",
    responses=documented_errors(status.HTTP_404_NOT_FOUND, *PROVIDER_FAILURES),
)
def delete_event(event_id: EventId, provider: Provider) -> Response:
    provider.delete_event(event_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
