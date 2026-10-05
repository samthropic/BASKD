"""Runtime configuration, read from environment variables (prefix ``BASKD_``) or ``.env``.

The service fails fast at startup with a readable message when the chosen provider is
missing its configuration, rather than failing on the first request.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["memory", "google"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


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

    log_level: LogLevel = "INFO"

    @field_validator(
        "google_credentials_file", "google_credentials_json", "google_calendar_id", mode="before"
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
