output "image_repository" {
  description = "Push release images here (then pass the pushed digest as var.image)."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "calendar_key_secret" {
  description = "Secret Manager secret that must hold the Calendar service-account key."
  value       = google_secret_manager_secret.calendar_key.secret_id
}

output "runtime_service_account" {
  description = "Identity the container runs as."
  value       = google_service_account.runtime.email
}

output "service_url" {
  description = "Base URL of the deployed API (null until an image is deployed)."
  value       = var.image == null ? null : google_cloud_run_v2_service.api[0].uri
}
