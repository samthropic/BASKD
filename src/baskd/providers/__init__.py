"""Concrete calendar backends and the single place that chooses between them."""

from __future__ import annotations

from baskd.ports import CalendarProvider
from baskd.providers.memory import InMemoryCalendarProvider
from baskd.settings import Settings


def build_provider(settings: Settings) -> CalendarProvider:
    """Instantiate the provider named by ``settings.provider``.

    This is the only function that knows every implementation; everything else depends
    on :class:`~baskd.ports.CalendarProvider`.
    """
    if settings.provider == "memory":
        return InMemoryCalendarProvider()
    if settings.provider == "google":
        # Imported lazily so running with the fake never touches the Google SDK.
        from baskd.providers.google import GoogleCalendarProvider

        return GoogleCalendarProvider.from_settings(settings)
    raise ValueError(f"Unknown provider {settings.provider!r}")  # pragma: no cover


__all__ = ["InMemoryCalendarProvider", "build_provider"]
