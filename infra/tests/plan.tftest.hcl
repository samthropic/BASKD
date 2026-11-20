# Offline checks of the plan: `terraform test` with a mocked Google provider, so they need no
# credentials and create nothing. Run from infra/: terraform init -backend=false && terraform test

mock_provider "google" {}

variables {
  calendar_id = "test-calendar@group.calendar.google.com"
}

run "first_apply_without_an_image_creates_no_service" {
  command = plan

  assert {
    condition     = length(google_cloud_run_v2_service.api) == 0
    error_message = "With no image yet, only the repository, secret and identity should be planned."
  }

  assert {
    condition     = google_secret_manager_secret.calendar_key.secret_id == "baskd-calendar-key"
    error_message = "prod's secret should keep the plain name."
  }
}

run "service_runs_the_pinned_image_with_the_key_mounted" {
  command = plan

  variables {
    image    = "us-east1-docker.pkg.dev/baskd-calendar/baskd/baskd@sha256:0000000000000000000000000000000000000000000000000000000000000000"
    invokers = ["user:grader@nyu.edu"]
  }

  assert {
    condition     = google_cloud_run_v2_service.api[0].template[0].containers[0].image == var.image
    error_message = "Cloud Run must run exactly the digest it was given."
  }

  assert {
    condition = contains(
      [for e in google_cloud_run_v2_service.api[0].template[0].containers[0].env : "${e.name}=${e.value}"],
      "BASKD_GOOGLE_CREDENTIALS_FILE=/run/secrets/baskd/service-account.json",
    )
    error_message = "The app must be pointed at the mounted key file."
  }

  assert {
    condition     = google_cloud_run_v2_service.api[0].template[0].containers[0].startup_probe[0].http_get[0].path == "/health"
    error_message = "Probes must use /health, which never calls Google."
  }

  assert {
    condition     = length(google_cloud_run_v2_service_iam_member.invokers) == 1
    error_message = "Each listed invoker gets roles/run.invoker, and no one else."
  }
}

run "nyu_domain_can_invoke" {
  command = plan

  variables {
    image    = "us-east1-docker.pkg.dev/baskd-calendar/baskd/baskd@sha256:0000000000000000000000000000000000000000000000000000000000000000"
    invokers = ["domain:nyu.edu"]
  }

  assert {
    condition     = google_cloud_run_v2_service_iam_member.invokers["domain:nyu.edu"].member == "domain:nyu.edu"
    error_message = "domain:nyu.edu is how course staff call the service (docs/DEPLOYMENT.md §4)."
  }

  assert {
    condition     = google_cloud_run_v2_service_iam_member.invokers["domain:nyu.edu"].role == "roles/run.invoker"
    error_message = "Invokers may only invoke."
  }
}

run "public_invokers_are_rejected" {
  command = plan

  variables {
    image    = "us-east1-docker.pkg.dev/baskd-calendar/baskd/baskd@sha256:0000000000000000000000000000000000000000000000000000000000000000"
    invokers = ["domain:nyu.edu", "allUsers"]
  }

  expect_failures = [var.invokers]
}

run "staging_never_shares_names_with_prod" {
  command = plan

  variables {
    environment = "staging"
  }

  assert {
    condition     = google_artifact_registry_repository.images.repository_id == "baskd-staging"
    error_message = "staging must have its own image repository."
  }

  assert {
    condition     = google_service_account.runtime.account_id == "baskd-staging-runtime"
    error_message = "staging must have its own runtime identity."
  }
}

run "a_mutable_tag_is_rejected" {
  command = plan

  variables {
    image = "us-east1-docker.pkg.dev/baskd-calendar/baskd/baskd:latest"
  }

  expect_failures = [var.image]
}

run "prod_deploys_only_from_v_tags_of_this_repository" {
  command = plan

  assert {
    condition = google_iam_workload_identity_pool_provider.github.attribute_condition == join(" && ", [
      "assertion.repository_id == '1373519725'",
      "assertion.ref_type == 'tag'",
      "assertion.ref.startsWith('refs/tags/v')",
    ])
    error_message = "prod's deploy identity must accept only v* tags from this repository."
  }

  assert {
    condition     = google_service_account.deploy.account_id != google_service_account.runtime.account_id
    error_message = "The deploy identity must be separate from the runtime identity."
  }
}

run "staging_deploys_only_from_staging_tags" {
  command = plan

  variables {
    environment = "staging"
  }

  assert {
    condition     = endswith(google_iam_workload_identity_pool_provider.github.attribute_condition, "assertion.ref.startsWith('refs/tags/staging-')")
    error_message = "staging's deploy identity must not accept release tags, and prod's must not accept drill tags."
  }

  assert {
    condition     = google_service_account.deploy.account_id == "baskd-staging-deploy"
    error_message = "staging must have its own deploy identity."
  }
}

run "telemetry_is_wired_and_metric_labels_stay_bounded" {
  command = plan

  variables {
    image = "us-east1-docker.pkg.dev/baskd-calendar/baskd/baskd@sha256:0000000000000000000000000000000000000000000000000000000000000000"
  }

  assert {
    condition = alltrue([
      for wanted in ["BASKD_LOG_FORMAT=json", "BASKD_GCP_PROJECT=baskd-calendar"] : contains(
        [for e in google_cloud_run_v2_service.api[0].template[0].containers[0].env : "${e.name}=${e.value}"],
        wanted,
      )
    ])
    error_message = "Cloud Run must write Cloud Logging JSON and export traces to the project."
  }

  assert {
    condition     = google_project_iam_member.runtime_writes_traces.role == "roles/cloudtrace.agent"
    error_message = "The runtime identity may only write traces, not read or administer them."
  }

  assert {
    condition = length(setintersection(
      keys(merge(google_logging_metric.requests.label_extractors, google_logging_metric.request_latency.label_extractors)),
      ["request_id", "trace_id", "route", "event_id"],
    )) == 0
    error_message = "Metric labels must stay bounded: no ids or paths."
  }
}

run "slo_counts_only_failures_that_are_ours_and_pages_a_real_inbox" {
  command = plan

  variables {
    alert_emails = ["oncall@nyu.edu"]
  }

  assert {
    condition     = strcontains(google_monitoring_slo.get_availability.request_based_sli[0].good_total_ratio[0].total_service_filter, "NOT metric.label.\"category\"=\"invalid_input\"")
    error_message = "A caller's invalid request must not count against our availability."
  }

  assert {
    condition = alltrue([
      for category in ["provider_failure", "access_denied", "internal"] :
      strcontains(google_monitoring_slo.get_availability.request_based_sli[0].good_total_ratio[0].bad_service_filter, "\"${category}\"")
    ])
    error_message = "Provider failures, access denials and bugs are the bad events."
  }

  assert {
    condition     = !strcontains(google_monitoring_slo.get_availability.request_based_sli[0].good_total_ratio[0].bad_service_filter, "not_found")
    error_message = "A 404 for a missing event is a correct answer, not a failure."
  }

  assert {
    condition     = google_monitoring_slo.get_latency.request_based_sli[0].distribution_cut[0].range[0].max == 1000
    error_message = "The latency threshold comes from the measured p95 (docs/SLO.md)."
  }

  assert {
    condition     = length(google_monitoring_notification_channel.email) == 1 && length(google_monitoring_alert_policy.get_availability_fast_burn.conditions) == 2
    error_message = "The alert must page the listed inbox and check both the 1-hour and 5-minute windows."
  }
}

run "staging_has_its_own_slo_service" {
  command = plan

  variables {
    environment = "staging"
  }

  assert {
    condition     = google_monitoring_custom_service.api.service_id == "baskd-staging-api"
    error_message = "A staging drill must never burn prod's error budget."
  }
}

run "workflow_defaults_to_our_memory_implementations_with_no_secret_env" {
  command = plan

  variables {
    image = "us-east1-docker.pkg.dev/baskd-calendar/baskd/baskd@sha256:0000000000000000000000000000000000000000000000000000000000000000"
  }

  assert {
    condition = alltrue([
      for wanted in ["BASKD_WORKFLOW_STORAGE=memory", "BASKD_WORKFLOW_ISSUES=memory"] : contains(
        [for e in google_cloud_run_v2_service.api[0].template[0].containers[0].env : "${e.name}=${e.value == null ? "" : e.value}"],
        wanted,
      )
    ])
    error_message = "Without a choice, the workflow must use our in-memory implementations."
  }

  assert {
    condition = length([
      for e in google_cloud_run_v2_service.api[0].template[0].containers[0].env : e.name
      if startswith(e.name, "DROPBOX_") || startswith(e.name, "TRELLO_")
    ]) == 0
    error_message = "A revision that does not use Dropbox or Trello must not depend on their secrets."
  }

  assert {
    condition     = length(google_secret_manager_secret.workflow) == 5 && google_secret_manager_secret.workflow["DROPBOX_REFRESH_TOKEN"].secret_id == "baskd-dropbox-refresh-token"
    error_message = "The five credential secrets exist (empty) whatever is chosen, so they can be filled before a switch."
  }
}

run "team3_and_team4_read_their_credentials_from_secret_manager" {
  command = plan

  variables {
    image            = "us-east1-docker.pkg.dev/baskd-calendar/baskd/baskd@sha256:0000000000000000000000000000000000000000000000000000000000000000"
    workflow_storage = "team3"
    workflow_issues  = "team4"
    trello_list_id   = "0123456789abcdef01234567"
  }

  assert {
    condition = toset([
      for e in google_cloud_run_v2_service.api[0].template[0].containers[0].env : e.name
      if length(e.value_source) > 0
      ]) == toset([
      "DROPBOX_APP_KEY", "DROPBOX_APP_SECRET", "DROPBOX_REFRESH_TOKEN", "TRELLO_API_KEY", "TRELLO_TOKEN",
    ])
    error_message = "Exactly the five credentials come from Secret Manager."
  }

  assert {
    condition = alltrue([
      for e in google_cloud_run_v2_service.api[0].template[0].containers[0].env :
      e.value_source[0].secret_key_ref[0].version == "latest" if length(e.value_source) > 0
    ])
    error_message = "Credentials follow the latest secret version, so a rotation needs no Terraform change."
  }

  assert {
    condition = contains(
      [for e in google_cloud_run_v2_service.api[0].template[0].containers[0].env : "${e.name}=${e.value == null ? "" : e.value}"],
      "TRELLO_LIST_ID=0123456789abcdef01234567",
    )
    error_message = "The list id is plain configuration, like the calendar id."
  }

  assert {
    condition = alltrue([
      for member in google_secret_manager_secret_iam_member.runtime_reads_workflow :
      member.role == "roles/secretmanager.secretAccessor"
    ]) && length(google_secret_manager_secret_iam_member.runtime_reads_workflow) == 5
    error_message = "The runtime identity may read each credential secret, and only read it."
  }
}

run "swapping_storage_to_team1_changes_only_configuration" {
  command = plan

  variables {
    image            = "us-east1-docker.pkg.dev/baskd-calendar/baskd/baskd@sha256:0000000000000000000000000000000000000000000000000000000000000000"
    workflow_storage = "team1"
  }

  assert {
    condition = contains(
      [for e in google_cloud_run_v2_service.api[0].template[0].containers[0].env : "${e.name}=${e.value == null ? "" : e.value}"],
      "BASKD_WORKFLOW_STORAGE=team1",
    )
    error_message = "The swap is one variable."
  }

  assert {
    condition = length([
      for e in google_cloud_run_v2_service.api[0].template[0].containers[0].env : e.name
      if startswith(e.name, "DROPBOX_")
    ]) == 3
    error_message = "Team 1 takes the same three Dropbox credentials as Team 3."
  }
}

run "trello_without_a_list_id_is_rejected" {
  command = plan

  variables {
    image           = "us-east1-docker.pkg.dev/baskd-calendar/baskd/baskd@sha256:0000000000000000000000000000000000000000000000000000000000000000"
    workflow_issues = "team4"
  }

  expect_failures = [google_cloud_run_v2_service.api]
}

run "unknown_implementation_is_rejected" {
  command = plan

  variables {
    workflow_storage = "team6"
  }

  expect_failures = [var.workflow_storage]
}

run "staging_has_its_own_credential_secrets" {
  command = plan

  variables {
    environment = "staging"
  }

  assert {
    condition     = google_secret_manager_secret.workflow["TRELLO_TOKEN"].secret_id == "baskd-staging-trello-token"
    error_message = "staging's credentials must never be prod's secrets."
  }
}
