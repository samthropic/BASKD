"""Runtime configuration, read from environment variables (prefix ``BASKD_``) or ``.env``.

The service fails fast at startup with a readable message when the chosen provider is
missing its configuration, rather than failing on the first request.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["memory", "google"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
LogFormat = Literal["text", "json"]
#: HW3: whose Document Storage the workflow uses (``memory`` and ``failing`` are ours).
StorageImplementation = Literal["team3", "team1", "memory", "failing"]
#: HW3: whose issue tracker the workflow uses (``memory`` and ``failing`` are ours).
IssueImplementation = Literal["team4", "memory", "failing"]

#: Environment variables the other teams' packages read themselves (not ``BASKD_``-prefixed,
#: and not read from ``.env``). Both Dropbox implementations take the same three.
DROPBOX_VARIABLES = ("DROPBOX_APP_KEY", "DROPBOX_APP_SECRET", "DROPBOX_REFRESH_TOKEN")
TRELLO_VARIABLES = ("TRELLO_API_KEY", "TRELLO_TOKEN", "TRELLO_LIST_ID")


class Settings(BaseSettings):
    """All knobs of the service. See ``.env.example`` for documentation of each one."""

    model_config = SettingsConfigDict(
        env_prefix="BASKD_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    provider: ProviderName = "memory"

    google_credentials_file: Path | None = None
    google_credentials_json: SecretStr | None = None
    google_calendar_id: str | None = None
    google_timeout_seconds: float = Field(default=10.0, gt=0, le=120)

    #: Storage behind the HW3 workflow: ``team3`` (Dropbox), ``team1`` (Dropbox), ``memory``,
    #: or ``failing`` (every call fails; for the failure demo).
    workflow_storage: StorageImplementation = "memory"
    #: Issue tracker behind the HW3 workflow: ``team4`` (Trello), ``memory`` or ``failing``.
    workflow_issues: IssueImplementation = "memory"

    log_level: LogLevel = "INFO"
    #: ``json`` writes Cloud Logging's structured format (set on Cloud Run by Terraform).
    log_format: LogFormat = "text"
    #: Google Cloud project that receives traces. Unset: spans are made but not exported.
    gcp_project: str | None = None
    #: Commit the image was built from (the Dockerfile bakes it in); part of the release.
    commit: str = "unknown"

    @field_validator(
        "google_credentials_file",
        "google_credentials_json",
        "google_calendar_id",
        "gcp_project",
        mode="before",
    )
    @classmethod
    def _blank_means_unset(cls, value: Any) -> Any:
        """Treat ``BASKD_X=`` (present but empty) the same as not set."""
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @model_validator(mode="after")
    def _google_needs_credentials_and_calendar(self) -> Settings:
        if self.provider != "google":
            return self
        problems: list[str] = []
        if not self.google_calendar_id:
            problems.append("BASKD_GOOGLE_CALENDAR_ID is required")
        if self.google_credentials_file is None and self.google_credentials_json is None:
            problems.append(
                "one of BASKD_GOOGLE_CREDENTIALS_FILE or BASKD_GOOGLE_CREDENTIALS_JSON is required"
            )
        if problems:
            raise ValueError("BASKD_PROVIDER=google but " + "; ".join(problems))
        return self

    @model_validator(mode="after")
    def _workflow_implementations_need_credentials(self) -> Settings:
        """Fail at startup, not on a user's request, when another team's package lacks its
        credentials. Only presence is checked; a wrong value fails on the first call."""
        problems: list[str] = []
        if self.workflow_storage in ("team3", "team1"):
            problems += _missing(
                DROPBOX_VARIABLES, f"BASKD_WORKFLOW_STORAGE={self.workflow_storage}"
            )
        if self.workflow_issues == "team4":
            problems += _missing(TRELLO_VARIABLES, "BASKD_WORKFLOW_ISSUES=team4")
        if problems:
            raise ValueError("; ".join(problems))
        return self


def _missing(names: tuple[str, ...], choice: str) -> list[str]:
    absent = [name for name in names if not os.environ.get(name, "").strip()]
    if not absent:
        return []
    return [f"{choice} needs {', '.join(absent)} in the environment"]
