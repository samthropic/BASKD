"""Dependency injection glue between FastAPI and the provider port.

The concrete provider is chosen once, in :func:`baskd.app.create_app`, and parked on
``app.state``. Routes declare ``provider: Provider`` and receive it per request. Tests pass
a fake straight into ``create_app(provider=...)``; no monkeypatching required.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, cast

from fastapi import Depends, Request
from starlette.datastructures import State

from baskd.ports import CalendarProvider


def get_provider(request: Request) -> CalendarProvider:
    provider = getattr(request.app.state, "provider", None)
    if provider is None:  # pragma: no cover - only reachable if create_app() is bypassed
        raise RuntimeError("No calendar provider configured; build the app with create_app()")
    return cast(CalendarProvider, _RecordsCalls(provider, request.state))


class _RecordsCalls:
    """Passes every call through to the provider, noting on ``request.state`` that it ran.

    Failure logs use the note to say whether the provider was involved: a ``422`` or a
    rejected cursor never reaches it, a ``404`` from the provider does.
    """

    def __init__(self, provider: CalendarProvider, state: State) -> None:
        self._provider = provider
        self._state = state

    def __getattr__(self, attribute: str) -> Any:
        target = getattr(self._provider, attribute)
        if not callable(target):
            return target

        def call(*args: Any, **kwargs: Any) -> Any:
            self._state.provider_called = True
            return cast(Callable[..., Any], target)(*args, **kwargs)

        return call


Provider = Annotated[CalendarProvider, Depends(get_provider)]
