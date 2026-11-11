variable "project_id" {
  description = "Google Cloud project that hosts the service (the one whose Calendar API the service already uses)."
  type        = string
  default     = "baskd-calendar"
}

variable "region" {
  description = "Region for Cloud Run and Artifact Registry."
  type        = string
  default     = "us-east1"
}

variable "environment" {
  description = "prod is the demonstrated service; staging is the disposable one for release drills. Each has its own state prefix and its own resources."
  type        = string
  default     = "prod"

  validation {
    condition     = contains(["prod", "staging"], var.environment)
    error_message = "environment must be prod or staging."
  }
}

variable "calendar_id" {
  description = "Id of the Google Calendar the service reads and writes (not secret, but environment-specific)."
  type        = string
}

variable "image" {
  description = "Container image to run, pinned by digest (REGION-docker.pkg.dev/PROJECT/REPO/baskd@sha256:...). Leave null on the first apply: the service is created once an image exists."
  type        = string
  default     = null

  validation {
    condition     = var.image == null || can(regex("@sha256:[0-9a-f]{64}$", var.image))
    error_message = "image must be pinned by digest (...@sha256:<64 hex>), never by a mutable tag such as latest."
  }
}

variable "invokers" {
  description = "Principals allowed to call the service, e.g. [\"user:someone@nyu.edu\"]. The service has no auth of its own, so it is private by default."
  type        = list(string)
  default     = []
}

variable "max_instances" {
  description = "Upper bound on Cloud Run instances. Caps cost and Google Calendar quota use."
  type        = number
  default     = 2
}

variable "concurrency" {
  description = "Requests one instance serves at once. Level 3 reports in-flight requests against this limit."
  type        = number
  default     = 20
}

variable "google_timeout_seconds" {
  description = "BASKD_GOOGLE_TIMEOUT_SECONDS: how long the service waits for one Google call."
  type        = number
  default     = 10
}
