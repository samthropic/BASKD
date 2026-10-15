"""Bind a pagination cursor to the ``from``/``to`` window it was issued for.

Providers issue their own opaque page tokens (an offset for the in-memory provider, Google's
``nextPageToken``). Presented with a different window, such a token would silently continue
some other listing, and what Google does with a mismatched ``pageToken`` is undocumented.
So the API wraps the provider's token together with the window, and a cursor presented
with any other window is rejected as ``400 invalid_request``. ``limit`` may change between
pages. The wrapper is not a security boundary: a client that decodes and edits a cursor
only gets what the provider makes of the edited token.
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import UTC, datetime

from baskd.errors import InvalidRequest
from baskd.models import ListEventsQuery


def wrap_cursor(provider_cursor: str | None, query: ListEventsQuery) -> str | None:
    """The cursor returned to the client for the provider's next-page token."""
    if provider_cursor is None:
        return None
    payload = json.dumps({"c": provider_cursor, "w": _window(query)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def unwrap_cursor(cursor: str | None, query: ListEventsQuery) -> str | None:
    """The provider's page token inside ``cursor``, if it was issued for ``query``'s window."""
    if cursor is None:
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        provider_cursor, window = payload["c"], payload["w"]
    except (binascii.Error, ValueError, KeyError, TypeError):
        raise InvalidRequest("Invalid cursor") from None
    if not isinstance(provider_cursor, str):
        raise InvalidRequest("Invalid cursor")
    if window != _window(query):
        raise InvalidRequest(
            "Cursor was issued for a different 'from'/'to'; repeat the original query "
            "or start again without a cursor"
        )
    return provider_cursor


def _window(query: ListEventsQuery) -> list[str | None]:
    return [_instant(query.time_min), _instant(query.time_max)]


def _instant(value: datetime | None) -> str | None:
    # Compare instants, not spellings: 11:00-04:00 and 15:00Z are the same bound.
    return None if value is None else value.astimezone(UTC).isoformat()
