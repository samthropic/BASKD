"""Provider-neutral error vocabulary.

Providers translate their own failures (HTTP status codes, SDK exceptions, socket
errors) into one of these exceptions. The HTTP layer (:mod:`baskd.api.errors`) maps each
one to a status code and a stable machine-readable ``code``. Nothing outside a provider
module should ever need to import a provider SDK's exception types.

Each class also states its ``category`` (which kind of failure a caller must be able to tell
apart it is) and whether repeating the same request may succeed (``retryable``). Both
appear in failure logs and in the README's error table.
"""


class CalendarError(Exception):
    """Base class for every error the service knows how to report."""

    #: Stable, machine-readable identifier surfaced in API error responses.
    code = "calendar_error"
    #: One of ``invalid_input``, ``not_found``, ``access_denied``, ``provider_failure``,
    #: ``internal``. Only used in logs; the public contract is ``code``.
    category = "internal"
    #: Whether repeating the identical request may succeed without anything else changing.
    retryable = False

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.__class__.__doc__ or self.code)

    @property
    def message(self) -> str:
        return str(self.args[0]) if self.args else self.code


class EventNotFound(CalendarError):
    """The requested event does not exist (or has been deleted)."""

    code = "not_found"
    category = "not_found"

    def __init__(self, event_id: str) -> None:
        super().__init__(f"Event {event_id!r} was not found")
        self.event_id = event_id


class InvalidRequest(CalendarError):
    """The provider rejected the request as invalid (e.g. a malformed pagination cursor)."""

    code = "invalid_input"
    category = "invalid_input"


#: ``InvalidRequest`` messages for events ``PUT`` refuses; shared so every provider agrees.
ALL_DAY_NOT_REPLACEABLE = "All-day events cannot be replaced through this API"
SERIES_NOT_REPLACEABLE = (
    "Recurring event series cannot be replaced; replace a single occurrence instead"
)


class ProviderUnavailable(CalendarError):
    """The provider is temporarily unavailable (timeout, network error, rate limit, 5xx).

    Retryable for reads, ``PUT`` and ``DELETE``. A create that timed out may still have
    succeeded at the provider, so callers should check before re-sending it.
    """

    code = "provider_unavailable"
    category = "provider_failure"
    retryable = True


class ProviderAuthError(CalendarError):
    """The provider rejected our credentials or we lack permission on the calendar.

    This is the service being denied, not the caller: the API has no caller identities, so
    it is the only access denial it can report, and only an operator can fix it.
    """

    code = "access_denied"
    category = "access_denied"


class ProviderError(CalendarError):
    """The provider failed in a way we did not anticipate.

    Not retryable: the outcome is unknown, so retrying a create could duplicate the event.
    Callers should re-read (``GET``/list) before repeating a write.
    """

    code = "provider_error"
    category = "provider_failure"
