terraform {
  required_version = ">= 1.8"
  backend "gcs" {
    # Bucket created by infra/terraform/bootstrap:
    #   terraform init -backend-config="bucket=<bootstrap output state_bucket>"
    prefix = "staging"
  }
  required_providers {
    google      = { source = "hashicorp/google", version = "~> 8.0" }
    google-beta = { source = "hashicorp/google-beta", version = "~> 8.0" }
  }
}

variable "project_id" {
  description = "Google Cloud project for the staging environment"
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
  default_labels = { project = "ai-recruiter", environment = "staging" }
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

module "platform" {
  source = "../../modules/platform"

  name                          = "ai-recruiter-staging"
  environment                   = "staging"
  project_id                    = var.project_id
  region                        = var.region
  github_workload_identity_pool = var.github_workload_identity_pool
  artifact_registry_repository  = var.artifact_registry_repository
  alert_email                   = var.alert_email
  push_images                   = true # staging builds and pushes; production deploys the same digests
  node_machine_type             = "e2-standard-4"
  node_min_per_zone             = 1
  node_max_per_zone             = 2
  db_tier                       = "db-custom-2-7680"
  db_high_availability          = false
  db_backup_retention_count     = 7
  redis_tier                    = "BASIC"
  redis_memory_gb               = 1
  subnet_cidr                   = "10.41.0.0/20"
  pods_cidr                     = "10.56.0.0/14"
  services_cidr                 = "10.60.0.0/20"
  master_cidr                   = "172.16.0.16/28"
}

output "platform" { value = module.platform }
