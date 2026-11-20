"""Application factory.

``create_app()`` with no arguments reads :class:`~baskd.settings.Settings` from the
environment and builds the configured provider, plus the storage and issue-tracker
implementations the HW3 workflow uses; this is what ``uvicorn --factory`` calls. Tests call
``create_app(settings=..., provider=..., storage=..., issues=...)`` to inject fakes.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from cloud_storage_api import DocumentStorage
from fastapi import FastAPI
from issue_tracker_contract import IssueProvider

from baskd import __version__
from baskd.api import events, health, workflows
from baskd.api.errors import register_error_handlers
from baskd.api.request_log import observe_request
from baskd.contract import ContractCalendarService
from baskd.ports import CalendarProvider
from baskd.providers import build_provider
from baskd.settings import Settings
from baskd.telemetry import configure_telemetry, release_of
from baskd.workflow.composition import build_issues, build_storage
from baskd.workflow.meeting_prep import MeetingPrep

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
    storage: DocumentStorage | None = None,
    issues: IssueProvider | None = None,
) -> FastAPI:
    settings = settings if settings is not None else Settings()
    configure_telemetry(settings)
    provider = provider if provider is not None else build_provider(settings)
    storage = storage if storage is not None else build_storage(settings)
    issues = issues if issues is not None else build_issues(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "BASK'D %s starting with provider=%s workflow_storage=%s workflow_issues=%s",
            release_of(settings),
            provider.name,
            settings.workflow_storage,
            settings.workflow_issues,
        )
        yield
        logger.info("BASK'D stopping")

    app = FastAPI(
        title="BASK'D Calendar API",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        # FastAPI's own spans record the raw path and query (event ids, time windows) and
        # would start a second trace; api/request_log.py makes the server span instead.
        telemetry={
            "tracing": False,
            "metrics": False,
            "logs": False,
            "operation_spans": False,
            "auto_configure": False,
        },
    )
    app.state.settings = settings
    app.state.provider = provider
    app.state.storage = storage
    app.state.issues = issues
    # The workflow reaches our calendar through the shared contract, like any other team would.
    app.state.meeting_prep = MeetingPrep(ContractCalendarService(provider), storage, issues)
    app.state.release = release_of(settings)
    app.middleware("http")(observe_request)
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(events.router)
    app.include_router(workflows.router)
    return app
