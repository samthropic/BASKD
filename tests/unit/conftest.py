"""Unit tests never see the developer's real configuration.

Any ``BASKD_*`` variable exported in the shell is removed for the duration of each test;
otherwise a teammate with ``BASKD_PROVIDER=google`` exported would see different behaviour
than CI. (``.env`` is handled by passing ``_env_file=None`` where ``Settings`` is built.)
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.startswith("BASKD_"):
            monkeypatch.delenv(name)
