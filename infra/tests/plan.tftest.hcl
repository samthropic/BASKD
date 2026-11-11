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
