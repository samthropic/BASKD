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
