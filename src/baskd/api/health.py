"""``/health`` (liveness) and ``/ready`` (readiness).

``/health`` does not call the provider, so it costs no quota and never flaps: platform probes
use it, and a Google outage cannot make them restart healthy instances in a loop.
``/ready`` makes one cheap provider call and answers 503 while the provider cannot serve
requests (outage, revoked key, calendar no longer shared). It tells an operator or a smoke
check whether requests would work right now; nothing restarts the service because of it.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from baskd import __version__
from baskd.api.dependencies import Provider
from baskd.errors import CalendarError

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    provider: str
    version: str


class ReadyResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    provider: str
    version: str
    reason: str | None = None


@router.get("/health", response_model=HealthResponse, summary="Liveness check")
def health(provider: Provider) -> HealthResponse:
    return HealthResponse(status="ok", provider=provider.name, version=__version__)


@router.get(
    "/ready",
    response_model=ReadyResponse,
    response_model_exclude_none=True,
    summary="Readiness check",
    description=(
        "Makes one cheap provider call. `200` when requests would work now; `503` with the "
        "error `code` as `reason` when they would not. Not used for liveness."
    ),
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadyResponse}},
)
def ready(provider: Provider) -> ReadyResponse | JSONResponse:
    try:
        provider.check_ready()
    except CalendarError as error:
        body = ReadyResponse(
            status="not_ready", provider=provider.name, version=__version__, reason=error.code
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=body.model_dump(exclude_none=True),
        )
    return ReadyResponse(status="ready", provider=provider.name, version=__version__)
