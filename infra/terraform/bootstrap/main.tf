# One-time bootstrap, run with an administrator's credentials:
#   - Terraform remote state bucket (GCS, versioned, CMEK)
#   - Shared Artifact Registry for container images (built once, promoted staging → production)
#   - Workload Identity Federation pool trusted by GitHub Actions (no service-account keys in GitHub)
terraform {
  required_version = ">= 1.8"
  required_providers {
    google      = { source = "hashicorp/google", version = "~> 8.0" }
    google-beta = { source = "hashicorp/google-beta", version = "~> 8.0" }
  }
}

variable "project_id" {
  description = "Project that holds shared resources (state, images, CI identity pool)"
  type        = string
}
variable "region" {
  type    = string
  default = "europe-west1"
}
variable "github_repository" {
  description = "owner/repo whose workflows may authenticate to Google Cloud"
  type        = string
  default     = "cjktechnologies/ai-recruiter"
}

provider "google" {
  project = var.project_id
  region  = var.region
}
provider "google-beta" {
  project = var.project_id
  region  = var.region
}

data "google_project" "this" {}

resource "google_project_service" "apis" {
  for_each = toset([
    "artifactregistry.googleapis.com", "cloudkms.googleapis.com", "cloudresourcemanager.googleapis.com",
    "containeranalysis.googleapis.com", "containerscanning.googleapis.com", "iam.googleapis.com",
    "iamcredentials.googleapis.com", "storage.googleapis.com", "sts.googleapis.com",
  ])
  service            = each.value
  disable_on_destroy = false
}

# ---------------------------------------------------------------------------------------------
# Encryption key for state and images
# ---------------------------------------------------------------------------------------------
resource "google_kms_key_ring" "shared" {
  name       = "ai-recruiter-shared"
  location   = var.region
  depends_on = [google_project_service.apis]
}
resource "google_kms_crypto_key" "shared" {
  name            = "shared"
  key_ring        = google_kms_key_ring.shared.id
  rotation_period = "7776000s" # 90 days
}

data "google_storage_project_service_account" "gcs" {
  depends_on = [google_project_service.apis]
}
resource "google_project_service_identity" "artifactregistry" {
  provider   = google-beta
  service    = "artifactregistry.googleapis.com"
  depends_on = [google_project_service.apis]
}
resource "google_kms_crypto_key_iam_member" "shared" {
  for_each = {
    storage          = "serviceAccount:${data.google_storage_project_service_account.gcs.email_address}"
    artifactregistry = google_project_service_identity.artifactregistry.member
  }
  crypto_key_id = google_kms_crypto_key.shared.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = each.value
}

# ---------------------------------------------------------------------------------------------
# Terraform state
# ---------------------------------------------------------------------------------------------
resource "google_storage_bucket" "state" {
  name                        = "${var.project_id}-ai-recruiter-tfstate"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  versioning { enabled = true }
  encryption { default_kms_key_name = google_kms_crypto_key.shared.id }
  lifecycle_rule {
    condition { num_newer_versions = 50 }
    action { type = "Delete" }
  }
  depends_on = [google_kms_crypto_key_iam_member.shared]
}

# ---------------------------------------------------------------------------------------------
# Container images: immutable tags, vulnerability scanning, keep the latest 100 versions
# ---------------------------------------------------------------------------------------------
resource "google_artifact_registry_repository" "images" {
  repository_id = "ai-recruiter"
  location      = var.region
  format        = "DOCKER"
  description   = "AI Recruiter container images (api, web)"
  kms_key_name  = google_kms_crypto_key.shared.id
  docker_config { immutable_tags = true }
  cleanup_policy_dry_run = false
  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions { keep_count = 100 }
  }
  cleanup_policies {
    id     = "delete-older"
    action = "DELETE"
    condition { tag_state = "ANY" }
  }
  depends_on = [google_kms_crypto_key_iam_member.shared]
}

# ---------------------------------------------------------------------------------------------
# GitHub Actions → Google Cloud via OIDC (Workload Identity Federation)
# Only workflows from var.github_repository can exchange tokens; each environment's deploy service
# account further restricts access to jobs running in that GitHub environment.
# ---------------------------------------------------------------------------------------------
resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github"
  display_name              = "GitHub Actions"
  depends_on                = [google_project_service.apis]
}
resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-actions"
  display_name                       = "GitHub Actions OIDC"
  attribute_mapping = {
    "google.subject"        = "assertion.sub"
    "attribute.repository"  = "assertion.repository"
    "attribute.environment" = "assertion.environment"
    "attribute.ref"         = "assertion.ref"
  }
  attribute_condition = "assertion.repository == '${var.github_repository}'"
  oidc { issuer_uri = "https://token.actions.githubusercontent.com" }
}

output "state_bucket" { value = google_storage_bucket.state.name }
output "artifact_registry_repository" { value = google_artifact_registry_repository.images.id }
output "image_registry" {
  description = "Prefix for image names, e.g. <this>/api:<sha>"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}
output "workload_identity_pool" { value = google_iam_workload_identity_pool.github.name }
output "workload_identity_provider" {
  description = "GitHub variable GCP_WORKLOAD_IDENTITY_PROVIDER"
  value       = google_iam_workload_identity_pool_provider.github.name
}
