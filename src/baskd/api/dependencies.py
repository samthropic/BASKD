"""Dependency injection glue between FastAPI and the provider port.

The concrete provider is chosen once, in :func:`baskd.app.create_app`, and parked on
``app.state``. Routes declare ``provider: Provider`` and receive it per request. Tests pass
a fake straight into ``create_app(provider=...)``; no monkeypatching required.
"""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Request

from baskd.ports import CalendarProvider


def get_provider(request: Request) -> CalendarProvider:
    provider = getattr(request.app.state, "provider", None)
    if provider is None:  # pragma: no cover - only reachable if create_app() is bypassed
        raise RuntimeError("No calendar provider configured; build the app with create_app()")
    return cast(CalendarProvider, provider)


Provider = Annotated[CalendarProvider, Depends(get_provider)]
