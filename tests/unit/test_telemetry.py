"""The Cloud Logging line format: what makes a log entry lead to its trace."""

from __future__ import annotations

import json
import logging

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import format_trace_id

from baskd.settings import Settings
from baskd.telemetry import CloudLoggingFormatter, release_of


def record(message: str, **extra: object) -> logging.LogRecord:
    entry = logging.LogRecord("baskd.requests", logging.WARNING, __file__, 1, message, None, None)
    entry.__dict__.update(extra)
    return entry


def test_request_line_becomes_a_structured_entry_linked_to_its_trace() -> None:
    tracer = TracerProvider().get_tracer("test")
    with tracer.start_as_current_span("request") as span:
        line = CloudLoggingFormatter("baskd-calendar").format(
            record("ignored", fields={"event": "request_failed", "status": 404})
        )
    entry = json.loads(line)
    trace_id = format_trace_id(span.get_span_context().trace_id)
    assert entry["severity"] == "WARNING"
    assert (entry["event"], entry["status"]) == ("request_failed", 404)
    assert entry["logging.googleapis.com/trace"] == f"projects/baskd-calendar/traces/{trace_id}"
    assert "message" not in entry


def test_other_lines_keep_their_message_and_have_no_trace_outside_a_request() -> None:
    entry = json.loads(CloudLoggingFormatter("baskd-calendar").format(record("starting")))
    assert entry == {"severity": "WARNING", "logger": "baskd.requests", "message": "starting"}


def test_release_is_version_plus_short_commit() -> None:
    settings = Settings(_env_file=None, commit="1a2b3c4d5e6f")
    assert release_of(settings).endswith("+1a2b3c4")
