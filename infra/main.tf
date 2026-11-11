locals {
  # prod keeps the plain name; any other environment gets a suffix, so a drill in staging
  # can never touch prod's service, image repository, secret or identity.
  name = var.environment == "prod" ? "baskd" : "baskd-${var.environment}"

  key_mount_dir = "/run/secrets/baskd"
  key_file      = "service-account.json"
}

# APIs this stack needs. They stay enabled on destroy: the Calendar API key and other
# environments may still depend on them.
resource "google_project_service" "apis" {
  for_each = toset([
    "artifactregistry.googleapis.com",
    "iam.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
  ])

  service            = each.value
  disable_on_destroy = false
}

# Where release images are pushed. Without it there is nothing for Cloud Run to pull.
resource "google_artifact_registry_repository" "images" {
  repository_id = local.name
  location      = var.region
  format        = "DOCKER"
  description   = "BASK'D release images (${var.environment})"

  depends_on = [google_project_service.apis]
}

# The identity the container runs as. It can read one secret and nothing else; it is not
# the identity that talks to Google Calendar (that one's key is in the secret).
resource "google_service_account" "runtime" {
  account_id   = "${local.name}-runtime"
  display_name = "BASK'D Cloud Run runtime (${var.environment})"

  depends_on = [google_project_service.apis]
}

# The Calendar service-account key. Terraform creates only the empty secret: the key itself
# is added with `gcloud secrets versions add` (README step 2), so it never enters the
# Terraform state, the repository or CI output.
resource "google_secret_manager_secret" "calendar_key" {
  secret_id = "${local.name}-calendar-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_iam_member" "runtime_reads_key" {
  secret_id = google_secret_manager_secret.calendar_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

# The service itself. Created only once an image digest is supplied (README step 3).
resource "google_cloud_run_v2_service" "api" {
  count = var.image == null ? 0 : 1

  name     = local.name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  # Lets `terraform destroy` remove the service (documented teardown).
  deletion_protection = false

  # Callers mint identity tokens for this audience instead of a URL, so one token works on the
  # service URL and on a release candidate's tagged URL (deploy.yml smoke-checks the candidate
  # before it gets traffic).
  custom_audiences = [local.name]

  # Terraform owns the service's configuration; the deploy workflow owns which image runs and
  # where traffic goes. `var.image` only seeds the first revision, so a release does not make
  # the next `terraform plan` want to roll the service back to that image.
  lifecycle {
    ignore_changes = [
      client,
      client_version,
      traffic,
      template[0].revision,
      template[0].labels,
      template[0].annotations,
      template[0].containers[0].image,
    ]
  }

  template {
    service_account                  = google_service_account.runtime.email
    max_instance_request_concurrency = var.concurrency
    timeout                          = "30s"

    scaling {
      min_instance_count = 0
      max_instance_count = var.max_instances
    }

    containers {
      image = var.image

      ports {
        container_port = 8000
      }

      env {
        name  = "BASKD_PROVIDER"
        value = "google"
      }
      env {
        name  = "BASKD_GOOGLE_CALENDAR_ID"
        value = var.calendar_id
      }
      env {
        name  = "BASKD_GOOGLE_CREDENTIALS_FILE"
        value = "${local.key_mount_dir}/${local.key_file}"
      }
      env {
        name  = "BASKD_GOOGLE_TIMEOUT_SECONDS"
        value = tostring(var.google_timeout_seconds)
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      # /health never calls Google, so a Google outage cannot fail these probes and make
      # Cloud Run restart healthy instances in a loop. A bad configuration still fails
      # fast: the app refuses to start (settings.py), and the startup probe never passes.
      startup_probe {
        http_get {
          path = "/health"
        }
        period_seconds    = 2
        failure_threshold = 15
      }
      liveness_probe {
        http_get {
          path = "/health"
        }
        period_seconds = 30
      }

      volume_mounts {
        name       = "calendar-key"
        mount_path = local.key_mount_dir
      }
    }

    volumes {
      name = "calendar-key"
      secret {
        secret = google_secret_manager_secret.calendar_key.secret_id
        items {
          version = "latest"
          path    = local.key_file
        }
      }
    }
  }

  depends_on = [google_secret_manager_secret_iam_member.runtime_reads_key]
}

# Who may call it. Private by default; add teammates and graders in `invokers`.
resource "google_cloud_run_v2_service_iam_member" "invokers" {
  for_each = var.image == null ? toset([]) : toset(var.invokers)

  name     = google_cloud_run_v2_service.api[0].name
  location = var.region
  role     = "roles/run.invoker"
  member   = each.value
}
