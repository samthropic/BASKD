"""Application factory.

``create_app()`` with no arguments reads :class:`~baskd.settings.Settings` from the
environment and builds the configured provider; this is what ``uvicorn --factory`` calls.
Tests call ``create_app(settings=..., provider=...)`` to inject a fake.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from baskd import __version__
from baskd.api import events, health
from baskd.api.errors import register_error_handlers
from baskd.ports import CalendarProvider
from baskd.providers import build_provider
from baskd.settings import Settings

logger = logging.getLogger(__name__)

DESCRIPTION = """\
A small calendar service in front of a real calendar provider.

* All timestamps you send must include a UTC offset (`Z` or `+hh:mm`); all timestamps
  you receive are UTC.
* Every error response has the shape `{"error": {"code": ..., "message": ...}}`.
* Listing uses *overlap* semantics: an event is returned when `event.end > from` and
  `event.start < to`.
"""


def create_app(
    settings: Settings | None = None,
    provider: CalendarProvider | None = None,
) -> FastAPI:
    settings = settings if settings is not None else Settings()
    _configure_logging(settings.log_level)
    provider = provider if provider is not None else build_provider(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info("BASK'D %s starting with provider=%s", __version__, provider.name)
        yield
        logger.info("BASK'D stopping")

    app = FastAPI(
        title="BASK'D Calendar API",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.provider = provider
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(events.router)
    return app


def _configure_logging(level: str) -> None:
    # Third-party libraries stay at WARNING; BASKD_LOG_LEVEL only governs our own loggers.
    # basicConfig is a no-op if the host process (e.g. uvicorn) already configured root.
    logging.basicConfig(
        level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("baskd").setLevel(level)
