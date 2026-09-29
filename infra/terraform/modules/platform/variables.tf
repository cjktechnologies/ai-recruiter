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
variable "region" { type = string }
variable "vpc_cidr" {
  type    = string
  default = "10.40.0.0/16"
}
variable "azs" {
  type    = list(string)
  default = []
}
variable "db_instance_class" {
  type    = string
  default = "db.r6g.large"
}
variable "db_allocated_storage" {
  type    = number
  default = 100
}
variable "db_multi_az" {
  type    = bool
  default = true
}
variable "db_backup_retention_days" {
  type    = number
  default = 30
}
variable "redis_node_type" {
  type    = string
  default = "cache.r7g.large"
}
variable "eks_version" {
  type    = string
  default = "1.31"
}
variable "node_instance_types" {
  type    = list(string)
  default = ["m7g.large"]
}
variable "node_min" {
  type    = number
  default = 3
}
variable "node_max" {
  type    = number
  default = 12
}
variable "document_retention_days" {
  description = "Noncurrent document versions are purged after this many days"
  type        = number
  default     = 30
}
variable "github_repository" {
  description = "owner/repo allowed to assume the CI deploy role via GitHub OIDC"
  type        = string
}
variable "tags" {
  type    = map(string)
  default = {}
}
