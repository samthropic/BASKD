# Level 4: the promise we make for GET /events/{id}, and the alert that tells us we're breaking it.
# docs/SLO.md explains every number here; change both together.
#
# Both SLIs are built from the Level 3 log-based metrics (observability.tf), so they measure what
# the service itself saw. They cannot see requests that never reached the container.

locals {
  get_requests = join(" ", [
    "metric.type=\"${local.requests_metric}\"",
    local.service_filter,
    "metric.label.\"operation\"=\"get_event\"",
  ])

  # Eligible: every get except the caller's own mistakes (invalid_input). A 404 for a missing
  # event is a correct answer, so it counts as good.
  availability_total = "${local.get_requests} NOT metric.label.\"category\"=\"invalid_input\""
  # Bad: failures that are ours or our provider's.
  availability_bad = "${local.get_requests} metric.label.\"category\"=one_of(\"provider_failure\", \"access_denied\", \"internal\")"

  get_latency_success = join(" ", [
    "metric.type=\"${local.latency_metric}\"",
    local.service_filter,
    "metric.label.\"operation\"=\"get_event\"",
    "metric.label.\"outcome\"=\"success\"",
  ])
}

resource "google_monitoring_custom_service" "api" {
  service_id   = "${local.name}-api"
  display_name = "BASK'D API (${var.environment})"

  depends_on = [google_project_service.apis]
}

resource "google_monitoring_slo" "get_availability" {
  service             = google_monitoring_custom_service.api.service_id
  slo_id              = "get-event-availability"
  display_name        = "GET /events/{id}: ${format("%g", var.availability_goal * 100)}% not failed on our side, 28 days"
  goal                = var.availability_goal
  rolling_period_days = 28

  request_based_sli {
    good_total_ratio {
      total_service_filter = local.availability_total
      bad_service_filter   = local.availability_bad
    }
  }
}

resource "google_monitoring_slo" "get_latency" {
  service             = google_monitoring_custom_service.api.service_id
  slo_id              = "get-event-latency"
  display_name        = "GET /events/{id}: ${format("%g", var.latency_goal * 100)}% of successes under ${var.latency_threshold_ms} ms, 28 days"
  goal                = var.latency_goal
  rolling_period_days = 28

  request_based_sli {
    distribution_cut {
      distribution_filter = local.get_latency_success
      range {
        max = var.latency_threshold_ms
      }
    }
  }
}

resource "google_monitoring_notification_channel" "email" {
  for_each = toset(var.alert_emails)

  display_name = "BASK'D on-call: ${each.value}"
  type         = "email"
  labels = {
    email_address = each.value
  }
}

# Fast burn: the error budget is going at 14.4x the sustainable rate, over the last hour AND
# the last 5 minutes. At that rate a 28-day budget is gone in under 2 days. The 1-hour window
# keeps one stray failure from paging; the 5-minute window lets the alert close soon after
# the failures stop (docs/SLO.md, "The alert").
resource "google_monitoring_alert_policy" "get_availability_fast_burn" {
  display_name = "BASK'D (${var.environment}): GET /events/{id} error budget burning fast"
  combiner     = "AND"

  conditions {
    display_name = "Burn rate over 14.4x, last 1 hour"
    condition_threshold {
      filter          = "select_slo_burn_rate(\"${google_monitoring_slo.get_availability.id}\", \"3600s\")"
      comparison      = "COMPARISON_GT"
      threshold_value = 14.4
      duration        = "0s"
    }
  }

  conditions {
    display_name = "Burn rate over 14.4x, last 5 minutes"
    condition_threshold {
      filter          = "select_slo_burn_rate(\"${google_monitoring_slo.get_availability.id}\", \"300s\")"
      comparison      = "COMPARISON_GT"
      threshold_value = 14.4
      duration        = "0s"
    }
  }

  notification_channels = [for channel in google_monitoring_notification_channel.email : channel.id]

  alert_strategy {
    auto_close = "1800s"
  }

  documentation {
    mime_type = "text/markdown"
    subject   = "BASK'D ${var.environment}: GET /events/{id} is failing on our side"
    content = join("\n", [
      "More than 14.4x the sustainable share of `GET /events/{id}` requests failed on our side (provider failure, access denied, or a bug), over the last hour and the last 5 minutes.",
      "",
      "1. [Dashboard](https://console.cloud.google.com/monitoring/dashboards/builder/${basename(google_monitoring_dashboard.service.id)}?project=${var.project_id}): the errors panel shows which category.",
      "2. Runbook: [docs/OPERATIONS.md §2](https://github.com/${var.github_repository}/blob/main/docs/OPERATIONS.md#2-runbook-likely-failures) has the row for each category.",
      "3. Error budget policy: [docs/SLO.md](https://github.com/${var.github_repository}/blob/main/docs/SLO.md#error-budget-policy).",
    ])
  }
}
