"""Logging and tracing setup, done once per process by :func:`baskd.app.create_app`.

Traces: every request gets a server span (``api/request_log.py``) and every Google call a
child span (``providers/google.py``). Spans are always created, so log lines always carry a
trace id; they are exported to Cloud Trace only when ``BASKD_GCP_PROJECT`` is set.

Logs: with ``BASKD_LOG_FORMAT=json`` every line is one JSON object in the shape Cloud Logging
parses (``severity``, plus ``logging.googleapis.com/trace`` so the Logs Explorer links a line
to its trace). The default ``text`` format is for running locally.

Metrics are not exported from here: Terraform builds log-based metrics from the
``request_succeeded`` / ``request_failed`` lines (``infra/observability.tf``).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_ON
from opentelemetry.trace import format_span_id, format_trace_id

from baskd import __version__
from baskd.settings import Settings


def release_of(settings: Settings) -> str:
    """``0.2.0+1a2b3c4``: the package version plus the commit the image was built from."""
    return f"{__version__}+{settings.commit[:7]}"


def configure_telemetry(settings: Settings) -> None:
    _configure_logging(settings)
    _configure_tracing(settings)


def _configure_logging(settings: Settings) -> None:
    # Third-party libraries stay at WARNING; BASKD_LOG_LEVEL only governs our own loggers.
    # basicConfig is a no-op if the host process already configured the root logger.
    handler = logging.StreamHandler()
    handler.setFormatter(
        CloudLoggingFormatter(settings.gcp_project)
        if settings.log_format == "json"
        else logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logging.basicConfig(level=logging.WARNING, handlers=[handler])
    logging.getLogger("baskd").setLevel(settings.log_level)


def _configure_tracing(settings: Settings) -> None:
    if isinstance(trace.get_tracer_provider(), TracerProvider):
        return  # already set up in this process (tests build many apps)
    # shortcut: every request is sampled; fine at our traffic (Cloud Trace's free tier is
    # 2.5M spans a month). Switch to a ratio sampler if traffic grows past that.
    provider = TracerProvider(
        sampler=ALWAYS_ON,
        resource=Resource.create(
            {"service.name": "baskd", "service.version": release_of(settings)}
        ),
    )
    if settings.gcp_project:
        # Imported here so tests and local runs never need Google Cloud credentials.
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

        provider.add_span_processor(
            BatchSpanProcessor(
                CloudTraceSpanExporter(project_id=settings.gcp_project)  # type: ignore[no-untyped-call]
            )
        )
    trace.set_tracer_provider(provider)


class CloudLoggingFormatter(logging.Formatter):
    """One JSON object per line, in the shape Cloud Logging turns into a structured entry.

    A record logged with ``extra={"fields": {...}}`` (the per-request line) is written as
    those fields; any other record as ``{"message": ...}``. Lines written inside a span get
    the trace and span ids Cloud Logging uses to link the line to its trace.
    """

    def __init__(self, project: str | None) -> None:
        super().__init__()
        self._project = project

    def format(self, record: logging.LogRecord) -> str:
        fields = getattr(record, "fields", None)
        entry: dict[str, Any] = {"severity": record.levelname, "logger": record.name}
        entry.update(fields if isinstance(fields, dict) else {"message": record.getMessage()})
        span = trace.get_current_span().get_span_context()
        if self._project and span.is_valid:
            trace_id = format_trace_id(span.trace_id)
            entry["logging.googleapis.com/trace"] = f"projects/{self._project}/traces/{trace_id}"
            entry["logging.googleapis.com/spanId"] = format_span_id(span.span_id)
        if record.exc_info:
            entry["stack_trace"] = self.formatException(record.exc_info)
        return json.dumps(entry)
