# The identity GitHub Actions deploys releases as (.github/workflows/deploy.yml).
#
# GitHub signs in through Workload Identity Federation, so there is no long-lived key in
# GitHub. Only tag pushes in this repository can use it: prod accepts `v*` tags and staging
# accepts `staging-*` tags, so a staging drill can never deploy to prod. Forks cannot push
# tags here, and their workflows get no token for this repository.
#
# The deploy identity is separate from the runtime identity. It can push images to this
# environment's repository, roll out revisions of this environment's service (running as the
# runtime identity), move traffic between them, and call the service for the smoke check.
# It cannot read the Calendar key, change IAM, or touch the other environment.

locals {
  deploy_tag_prefix = var.environment == "prod" ? "refs/tags/v" : "refs/tags/staging-"
}

resource "google_project_service" "deploy_apis" {
  for_each = toset([
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
  ])

  service            = each.value
  disable_on_destroy = false
}

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "${local.name}-github"
  display_name              = "GitHub Actions (${var.environment})"
  description               = "Release deploys from ${var.github_repository}"

  depends_on = [google_project_service.deploy_apis]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub OIDC"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }

  # Checked on every token exchange: this repository (by id, so a renamed or re-created
  # repository with the same name does not inherit access) and this environment's tags only.
  attribute_condition = join(" && ", [
    "assertion.repository_id == '${var.github_repository_id}'",
    "assertion.ref_type == 'tag'",
    "assertion.ref.startsWith('${local.deploy_tag_prefix}')",
  ])

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account" "deploy" {
  account_id   = "${local.name}-deploy"
  display_name = "BASK'D release deploys from GitHub (${var.environment})"

  depends_on = [google_project_service.apis]
}

resource "google_service_account_iam_member" "github_impersonates_deploy" {
  service_account_id = google_service_account.deploy.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repository}"
}

resource "google_artifact_registry_repository_iam_member" "deploy_pushes_images" {
  repository = google_artifact_registry_repository.images.name
  location   = var.region
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.deploy.email}"
}

# Revisions run as the runtime identity, so deploying one needs actAs on it.
resource "google_service_account_iam_member" "deploy_acts_as_runtime" {
  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deploy.email}"
}

# Roll out revisions and move traffic on this environment's service only.
resource "google_cloud_run_v2_service_iam_member" "deploy_rolls_out" {
  count = var.image == null ? 0 : 1

  name     = google_cloud_run_v2_service.api[0].name
  location = var.region
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.deploy.email}"
}

# The smoke check calls the private service as the deploy identity.
resource "google_cloud_run_v2_service_iam_member" "deploy_runs_smoke_check" {
  count = var.image == null ? 0 : 1

  name     = google_cloud_run_v2_service.api[0].name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.deploy.email}"
}
