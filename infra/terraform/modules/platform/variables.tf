variable "name" {
  description = "Resource name prefix, e.g. ai-recruiter-staging"
  type        = string
}
variable "environment" {
  type = string
  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be staging or production"
  }
}
variable "project_id" { type = string }
variable "region" { type = string }

# --- Shared resources created by infra/terraform/bootstrap -----------------------------------
variable "github_workload_identity_pool" {
  description = "Bootstrap output workload_identity_pool (projects/<number>/locations/global/workloadIdentityPools/github)"
  type        = string
}
variable "artifact_registry_repository" {
  description = "Bootstrap output artifact_registry_repository (projects/<p>/locations/<l>/repositories/<r>)"
  type        = string
}
variable "push_images" {
  description = "Allow this environment's deploy identity to push images (the environment that builds them)"
  type        = bool
  default     = false
}

# --- Network ----------------------------------------------------------------------------------
variable "subnet_cidr" {
  type    = string
  default = "10.40.0.0/20"
}
variable "pods_cidr" {
  type    = string
  default = "10.48.0.0/14"
}
variable "services_cidr" {
  type    = string
  default = "10.52.0.0/20"
}
variable "master_cidr" {
  type    = string
  default = "172.16.0.0/28"
}
variable "master_authorized_cidrs" {
  description = "CIDRs allowed to reach the control plane's public IP. CI and operators use the IAM-gated DNS endpoint instead."
  type        = list(string)
  default     = []
}

# --- GKE --------------------------------------------------------------------------------------
variable "gke_release_channel" {
  type    = string
  default = "REGULAR"
}
variable "node_machine_type" {
  type    = string
  default = "n2-standard-4"
}
variable "node_min_per_zone" {
  type    = number
  default = 1
}
variable "node_max_per_zone" {
  type    = number
  default = 4
}

# --- Cloud SQL --------------------------------------------------------------------------------
variable "db_tier" {
  type    = string
  default = "db-custom-4-16384"
}
variable "db_disk_size_gb" {
  type    = number
  default = 100
}
variable "db_high_availability" {
  type    = bool
  default = true
}
variable "db_backup_retention_count" {
  description = "Daily backups kept"
  type        = number
  default     = 30
}
variable "db_backup_location" {
  description = "Multi-region for backups (disaster recovery), e.g. eu"
  type        = string
  default     = "eu"
}

# --- Memorystore ------------------------------------------------------------------------------
variable "redis_tier" {
  type    = string
  default = "STANDARD_HA"
}
variable "redis_memory_gb" {
  type    = number
  default = 5
}

# --- Storage / edge / alerting ----------------------------------------------------------------
variable "document_retention_days" {
  description = "Noncurrent document versions are purged after this many days"
  type        = number
  default     = 30
}
variable "waf_preview" {
  description = "Log Cloud Armor WAF matches without blocking (for tuning false positives)"
  type        = bool
  default     = false
}
variable "alert_email" {
  description = "Email for Cloud Monitoring alerts (empty = no notification channel)"
  type        = string
  default     = ""
}
variable "labels" {
  type    = map(string)
  default = {}
}
