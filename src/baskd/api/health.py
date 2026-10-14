"""``/health``: liveness. Does not call the provider, so it costs no quota and never flaps."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from baskd import __version__
from baskd.api.dependencies import Provider

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    provider: str
    version: str


@router.get("/health", response_model=HealthResponse, summary="Liveness check")
def health(provider: Provider) -> HealthResponse:
    return HealthResponse(status="ok", provider=provider.name, version=__version__)
