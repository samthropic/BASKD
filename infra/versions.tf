terraform {
  required_version = ">= 1.6"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.0"
    }
  }

  # State lives in a versioned GCS bucket shared by the team, never on one laptop.
  # The bucket and the prefix (one per environment) are passed at init time; see README.md.
  backend "gcs" {}
}

provider "google" {
  project = var.project_id
  region  = var.region
}
