"""Configuration loading and provider selection in the app factory."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from baskd.app import create_app
from baskd.providers import build_provider
from baskd.providers.google import GoogleCalendarProvider, load_credentials
from baskd.providers.memory import InMemoryCalendarProvider
from baskd.settings import Settings

SERVICE_ACCOUNT_EMAIL = "robot@baskd-test.iam.gserviceaccount.com"


@pytest.fixture(scope="module")
def service_account_info() -> dict[str, str]:
    """A structurally valid service-account key with a throwaway RSA key.

    google-auth parses the private key when building credentials but requests no token
    until the first API call, so this never touches the network.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return {
        "type": "service_account",
        "project_id": "baskd-test",
        "private_key_id": "key1",
        "private_key": pem,
        "client_email": SERVICE_ACCOUNT_EMAIL,
        "client_id": "1234567890",
        "token_uri": "https://oauth2.googleapis.com/token",
    }


class TestSettings:
    def test_defaults_to_memory_provider(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.provider == "memory"
        assert settings.log_level == "INFO"

    def test_reads_prefixed_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BASKD_PROVIDER", "google")
        monkeypatch.setenv("BASKD_GOOGLE_CALENDAR_ID", "cal@group.calendar.google.com")
        monkeypatch.setenv("BASKD_GOOGLE_CREDENTIALS_FILE", "secrets/sa.json")
        monkeypatch.setenv("BASKD_GOOGLE_TIMEOUT_SECONDS", "2.5")
        settings = Settings(_env_file=None)
        assert settings.provider == "google"
        assert settings.google_calendar_id == "cal@group.calendar.google.com"
        assert settings.google_credentials_file == Path("secrets/sa.json")
        assert settings.google_timeout_seconds == 2.5

    def test_google_requires_calendar_and_credentials(self) -> None:
        with pytest.raises(ValidationError, match="BASKD_GOOGLE_CALENDAR_ID is required") as info:
            Settings(provider="google", _env_file=None)
        assert "BASKD_GOOGLE_CREDENTIALS_FILE or BASKD_GOOGLE_CREDENTIALS_JSON" in str(info.value)

    def test_blank_values_count_as_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BASKD_PROVIDER", "google")
        monkeypatch.setenv("BASKD_GOOGLE_CALENDAR_ID", "")
        monkeypatch.setenv("BASKD_GOOGLE_CREDENTIALS_FILE", "  ")
        with pytest.raises(ValidationError, match="BASKD_GOOGLE_CALENDAR_ID is required"):
            Settings(_env_file=None)

    def test_rejects_unknown_provider(self) -> None:
        with pytest.raises(ValidationError):
            Settings(provider="outlook", _env_file=None)  # type: ignore[arg-type]

    def test_credentials_json_is_secret(self) -> None:
        settings = Settings(
            provider="google",
            google_calendar_id="cal",
            google_credentials_json='{"type": "service_account"}',
            _env_file=None,
        )
        assert "service_account" not in repr(settings)


class TestCredentialLoading:
    def test_from_file(self, tmp_path: Path, service_account_info: dict[str, str]) -> None:
        key_file = tmp_path / "sa.json"
        key_file.write_text(json.dumps(service_account_info))
        settings = Settings(
            provider="google",
            google_calendar_id="cal",
            google_credentials_file=key_file,
            _env_file=None,
        )
        credentials = load_credentials(settings)
        assert credentials.service_account_email == SERVICE_ACCOUNT_EMAIL
        assert "https://www.googleapis.com/auth/calendar.events" in credentials.scopes

    def test_from_inline_json(self, service_account_info: dict[str, str]) -> None:
        settings = Settings(
            provider="google",
            google_calendar_id="cal",
            google_credentials_json=json.dumps(service_account_info),
            _env_file=None,
        )
        credentials = load_credentials(settings)
        assert credentials.service_account_email == SERVICE_ACCOUNT_EMAIL

    def test_missing_file_is_a_clear_error(self, tmp_path: Path) -> None:
        settings = Settings(
            provider="google",
            google_calendar_id="cal",
            google_credentials_file=tmp_path / "nope.json",
            _env_file=None,
        )
        with pytest.raises(FileNotFoundError, match=r"nope\.json"):
            load_credentials(settings)

    def test_invalid_inline_json_is_a_clear_error(self) -> None:
        settings = Settings(
            provider="google",
            google_calendar_id="cal",
            google_credentials_json="{not json",
            _env_file=None,
        )
        with pytest.raises(ValueError, match="not valid JSON"):
            load_credentials(settings)


class TestBuildProvider:
    def test_memory(self) -> None:
        assert isinstance(
            build_provider(Settings(provider="memory", _env_file=None)), InMemoryCalendarProvider
        )

    def test_google_is_built_offline(
        self, tmp_path: Path, service_account_info: dict[str, str]
    ) -> None:
        key_file = tmp_path / "sa.json"
        key_file.write_text(json.dumps(service_account_info))
        settings = Settings(
            provider="google",
            google_calendar_id="cal@group.calendar.google.com",
            google_credentials_file=key_file,
            _env_file=None,
        )
        provider = build_provider(settings)
        assert isinstance(provider, GoogleCalendarProvider)
        assert provider.name == "google"


class TestCreateApp:
    def test_reads_settings_from_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BASKD_PROVIDER", "memory")
        monkeypatch.setenv("BASKD_LOG_LEVEL", "DEBUG")
        app = create_app()
        assert app.state.settings.log_level == "DEBUG"
        with TestClient(app) as client:
            assert client.get("/health").json()["provider"] == "memory"

    def test_injected_provider_wins_over_settings(self) -> None:
        marker = InMemoryCalendarProvider()
        app = create_app(settings=Settings(provider="memory", _env_file=None), provider=marker)
        assert app.state.provider is marker
