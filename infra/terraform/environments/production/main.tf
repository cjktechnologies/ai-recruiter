terraform {
  required_version = ">= 1.8"
  backend "gcs" {
    # Bucket created by infra/terraform/bootstrap:
    #   terraform init -backend-config="bucket=<bootstrap output state_bucket>"
    prefix = "production"
  }
  required_providers {
    google      = { source = "hashicorp/google", version = "~> 8.0" }
    google-beta = { source = "hashicorp/google-beta", version = "~> 8.0" }
  }
}

variable "project_id" {
  description = "Google Cloud project for the production environment"
  type        = string
}
variable "region" {
  type    = string
  default = "europe-west1"
}
variable "github_workload_identity_pool" {
  description = "Bootstrap output workload_identity_pool"
  type        = string
}
variable "artifact_registry_repository" {
  description = "Bootstrap output artifact_registry_repository"
  type        = string
}
variable "alert_email" {
  type    = string
  default = ""
}

provider "google" {
  project        = var.project_id
  region         = var.region
  default_labels = { project = "ai-recruiter", environment = "production" }
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

module "platform" {
  source = "../../modules/platform"

  name                          = "ai-recruiter-production"
  environment                   = "production"
  project_id                    = var.project_id
  region                        = var.region
  github_workload_identity_pool = var.github_workload_identity_pool
  artifact_registry_repository  = var.artifact_registry_repository
  alert_email                   = var.alert_email
}

output "platform" { value = module.platform }
