"""Provider-neutral error vocabulary.

Providers translate their own failures (HTTP status codes, SDK exceptions, socket
errors) into one of these exceptions. The HTTP layer (:mod:`baskd.api.errors`) maps each
one to a status code and a stable machine-readable ``code``. Nothing outside a provider
module should ever need to import a provider SDK's exception types.
"""


class CalendarError(Exception):
    """Base class for every error the service knows how to report."""

    #: Stable, machine-readable identifier surfaced in API error responses.
    code = "calendar_error"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.__class__.__doc__ or self.code)

    @property
    def message(self) -> str:
        return str(self.args[0]) if self.args else self.code


class EventNotFound(CalendarError):
    """The requested event does not exist (or has been deleted)."""

    code = "event_not_found"

    def __init__(self, event_id: str) -> None:
        super().__init__(f"Event {event_id!r} was not found")
        self.event_id = event_id


class InvalidRequest(CalendarError):
    """The provider rejected the request as invalid (e.g. a malformed pagination cursor)."""

    code = "invalid_request"


class ProviderUnavailable(CalendarError):
    """The provider is temporarily unavailable (timeout, network error, rate limit, 5xx)."""

    code = "provider_unavailable"


class ProviderAuthError(CalendarError):
    """The provider rejected our credentials or we lack permission on the calendar."""

    code = "provider_auth_error"


class ProviderError(CalendarError):
    """The provider failed in a way we did not anticipate."""

    code = "provider_error"
