# Level 3: metrics and the dashboard.
#
# The app writes one JSON line per request (src/baskd/api/request_log.py). Cloud Logging turns
# those lines into two log-based metrics, so the app exports no metrics of its own:
#   <name>_requests         count, by operation, outcome, error category, status and release
#   <name>_request_latency  distribution of latency_ms, by operation, outcome and release
# Saturation comes from Cloud Run's own metric: concurrent requests per instance, against
# var.concurrency. Traces go from the app straight to Cloud Trace (main.tf, runtime role).
#
# Labels hold only bounded values: 6 operations, 2 outcomes, 6 categories, a few statuses
# and one release per deploy. Never event ids, paths, titles or request ids.

locals {
  request_log_filter = join(" AND ", [
    "resource.type=\"cloud_run_revision\"",
    "resource.labels.service_name=\"${local.name}\"",
    "jsonPayload.event=(\"request_succeeded\" OR \"request_failed\")",
  ])

  requests_metric = "logging.googleapis.com/user/${google_logging_metric.requests.name}"
  latency_metric  = "logging.googleapis.com/user/${google_logging_metric.request_latency.name}"
  service_filter  = "resource.type=\"cloud_run_revision\" resource.label.\"service_name\"=\"${local.name}\""

  logs_url   = "https://console.cloud.google.com/logs/query;query=${urlencode(local.request_log_filter)}?project=${var.project_id}"
  traces_url = "https://console.cloud.google.com/traces/list?project=${var.project_id}"
}

resource "google_logging_metric" "requests" {
  name        = "${local.name}_requests"
  description = "BASK'D requests (${var.environment}), one per request_succeeded/request_failed log line."
  filter      = local.request_log_filter

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"

    labels {
      key         = "operation"
      description = "Route name: create_event, get_event, list_events, replace_event, delete_event, or unknown."
    }
    labels {
      key         = "outcome"
      description = "success or failure."
    }
    labels {
      key         = "category"
      description = "Error category (not_found, invalid_input, access_denied, provider_failure, internal); empty on success."
    }
    labels {
      key         = "status"
      description = "HTTP status code."
    }
    labels {
      key         = "release"
      description = "Package version plus commit, e.g. 0.2.0+1a2b3c4."
    }
  }

  label_extractors = {
    operation = "EXTRACT(jsonPayload.operation)"
    outcome   = "EXTRACT(jsonPayload.outcome)"
    category  = "EXTRACT(jsonPayload.category)"
    status    = "EXTRACT(jsonPayload.status)"
    release   = "EXTRACT(jsonPayload.release)"
  }

  depends_on = [google_project_service.apis]
}

resource "google_logging_metric" "request_latency" {
  name            = "${local.name}_request_latency"
  description     = "BASK'D server-side request latency in ms (${var.environment}), measured by the app."
  filter          = local.request_log_filter
  value_extractor = "EXTRACT(jsonPayload.latency_ms)"

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "DISTRIBUTION"
    unit        = "ms"

    labels {
      key = "operation"
    }
    labels {
      key = "outcome"
    }
    labels {
      key = "release"
    }
  }

  label_extractors = {
    operation = "EXTRACT(jsonPayload.operation)"
    outcome   = "EXTRACT(jsonPayload.outcome)"
    release   = "EXTRACT(jsonPayload.release)"
  }

  # 1 ms up to about 11 minutes, each bucket 40% wider than the last.
  bucket_options {
    exponential_buckets {
      num_finite_buckets = 40
      growth_factor      = 1.4
      scale              = 1
    }
  }

  depends_on = [google_project_service.apis]
}

locals {
  # One chart per signal. Each answers one question an operator acts on (docs/OBSERVABILITY.md).
  charts = [
    {
      title     = "Traffic: requests per minute, by operation"
      filter    = "metric.type=\"${local.requests_metric}\" ${local.service_filter}"
      aligner   = "ALIGN_DELTA"
      reducer   = "REDUCE_SUM"
      group_by  = ["metric.label.\"operation\""]
      threshold = null
    },
    {
      title     = "Errors per minute, by operation and error category"
      filter    = "metric.type=\"${local.requests_metric}\" ${local.service_filter} metric.label.\"outcome\"=\"failure\""
      aligner   = "ALIGN_DELTA"
      reducer   = "REDUCE_SUM"
      group_by  = ["metric.label.\"operation\"", "metric.label.\"category\""]
      threshold = null
    },
    {
      title     = "Latency p95 (ms), successful requests, by operation"
      filter    = "metric.type=\"${local.latency_metric}\" ${local.service_filter} metric.label.\"outcome\"=\"success\""
      aligner   = "ALIGN_DELTA"
      reducer   = "REDUCE_PERCENTILE_95"
      group_by  = ["metric.label.\"operation\""]
      threshold = null
    },
    {
      title     = "Latency p95 (ms), failed requests, by operation"
      filter    = "metric.type=\"${local.latency_metric}\" ${local.service_filter} metric.label.\"outcome\"=\"failure\""
      aligner   = "ALIGN_DELTA"
      reducer   = "REDUCE_PERCENTILE_95"
      group_by  = ["metric.label.\"operation\""]
      threshold = null
    },
    {
      title     = "Saturation: concurrent requests per instance (p99) vs. the limit of ${var.concurrency}"
      filter    = "metric.type=\"run.googleapis.com/container/max_request_concurrencies\" ${local.service_filter}"
      aligner   = "ALIGN_DELTA"
      reducer   = "REDUCE_PERCENTILE_99"
      group_by  = []
      threshold = var.concurrency
    },
    {
      title     = "Deployed release: requests per minute, by release"
      filter    = "metric.type=\"${local.requests_metric}\" ${local.service_filter}"
      aligner   = "ALIGN_DELTA"
      reducer   = "REDUCE_SUM"
      group_by  = ["metric.label.\"release\""]
      threshold = null
    },
  ]
}

resource "google_monitoring_dashboard" "service" {
  dashboard_json = jsonencode({
    displayName = "BASK'D (${var.environment})"
    mosaicLayout = {
      columns = 12
      tiles = concat(
        [
          for i, chart in local.charts : {
            xPos   = (i % 2) * 6
            yPos   = floor(i / 2) * 4
            width  = 6
            height = 4
            widget = {
              title = chart.title
              xyChart = merge(
                {
                  dataSets = [{
                    plotType = "LINE"
                    timeSeriesQuery = {
                      timeSeriesFilter = {
                        filter = chart.filter
                        aggregation = merge(
                          {
                            alignmentPeriod    = "60s"
                            perSeriesAligner   = chart.aligner
                            crossSeriesReducer = chart.reducer
                          },
                          length(chart.group_by) > 0 ? { groupByFields = chart.group_by } : {},
                        )
                      }
                    }
                  }]
                },
                chart.threshold == null ? {} : {
                  thresholds = [{ value = chart.threshold, label = "concurrency limit" }]
                },
              )
            }
          }
        ],
        [{
          xPos   = 0
          yPos   = 12
          width  = 12
          height = 3
          widget = {
            title = "From a panel to one request"
            text = {
              format = "MARKDOWN"
              content = join("\n", [
                "1. Spot the operation and error category in the panels above.",
                "2. [Request log lines](${local.logs_url}): add `jsonPayload.operation=\"get_event\"` or `jsonPayload.category=\"provider_failure\"`. Each line has `release`, `status`, `latency_ms` and `request_id` (the `X-Request-ID` the caller got).",
                "3. Open a line's trace from the Logs Explorer (the trace link on the entry), or [Trace Explorer](${local.traces_url}). The `google calendar.events.*` span is the call to Google; the rest of the server span is our own work.",
                "Walkthrough and what each panel is for: docs/OBSERVABILITY.md.",
              ])
            }
          }
        }],
      )
    }
  })

  depends_on = [google_project_service.apis]
}
