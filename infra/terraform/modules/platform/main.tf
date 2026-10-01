data "google_project" "this" { project_id = var.project_id }

locals {
  prod           = var.environment == "production"
  project_number = data.google_project.this.number
  labels         = merge(var.labels, { application = "ai-recruiter", environment = var.environment, managed-by = "terraform" })
  # GKE Workload Identity principals (no Google service accounts or keys for pods).
  wi_pool       = "principal://iam.googleapis.com/projects/${local.project_number}/locations/global/workloadIdentityPools/${var.project_id}.svc.id.goog"
  app_principal = "${local.wi_pool}/subject/ns/ai-recruiter/sa/ai-recruiter"
  eso_principal = "${local.wi_pool}/subject/ns/external-secrets/sa/external-secrets"
  registry      = regex("projects/(?P<project>[^/]+)/locations/(?P<location>[^/]+)/repositories/(?P<repository>[^/]+)", var.artifact_registry_repository)
}

resource "google_project_service" "apis" {
  for_each = toset([
    "cloudkms.googleapis.com", "compute.googleapis.com", "container.googleapis.com", "iam.googleapis.com",
    "logging.googleapis.com", "monitoring.googleapis.com", "redis.googleapis.com", "secretmanager.googleapis.com",
    "servicenetworking.googleapis.com", "sqladmin.googleapis.com", "storage.googleapis.com",
  ])
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# ---------------------------------------------------------------------------------------------
# Encryption: one Cloud KMS key for this environment's data at rest (Cloud SQL, Memorystore,
# Cloud Storage, Secret Manager, GKE Secrets), rotated every 90 days.
# ---------------------------------------------------------------------------------------------
resource "google_kms_key_ring" "main" {
  project    = var.project_id
  name       = var.name
  location   = var.region
  depends_on = [google_project_service.apis]
}
resource "google_kms_crypto_key" "data" {
  name            = "data"
  key_ring        = google_kms_key_ring.main.id
  rotation_period = "7776000s"
  labels          = local.labels
}

resource "google_project_service_identity" "agents" {
  provider   = google-beta
  for_each   = toset(["sqladmin.googleapis.com", "secretmanager.googleapis.com", "redis.googleapis.com"])
  project    = var.project_id
  service    = each.value
  depends_on = [google_project_service.apis]
}
data "google_storage_project_service_account" "gcs" {
  project    = var.project_id
  depends_on = [google_project_service.apis]
}
resource "google_kms_crypto_key_iam_member" "agents" {
  for_each = {
    cloudsql      = google_project_service_identity.agents["sqladmin.googleapis.com"].member
    secretmanager = google_project_service_identity.agents["secretmanager.googleapis.com"].member
    redis         = google_project_service_identity.agents["redis.googleapis.com"].member
    storage       = "serviceAccount:${data.google_storage_project_service_account.gcs.email_address}"
    gke           = "serviceAccount:service-${local.project_number}@container-engine-robot.iam.gserviceaccount.com"
  }
  crypto_key_id = google_kms_crypto_key.data.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = each.value
}

# ---------------------------------------------------------------------------------------------
# Network: VPC-native subnet with secondary ranges, Cloud NAT for egress, flow logs, and private
# services access so Cloud SQL and Memorystore have private IPs only.
# ---------------------------------------------------------------------------------------------
resource "google_compute_network" "main" {
  project                 = var.project_id
  name                    = var.name
  auto_create_subnetworks = false
  depends_on              = [google_project_service.apis]
}
resource "google_compute_subnetwork" "gke" {
  project                  = var.project_id
  name                     = "${var.name}-gke"
  region                   = var.region
  network                  = google_compute_network.main.id
  ip_cidr_range            = var.subnet_cidr
  private_ip_google_access = true
  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = var.pods_cidr
  }
  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = var.services_cidr
  }
  log_config {
    aggregation_interval = "INTERVAL_5_SEC"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }
}
resource "google_compute_router" "main" {
  project = var.project_id
  name    = var.name
  region  = var.region
  network = google_compute_network.main.id
}
resource "google_compute_router_nat" "main" {
  project                            = var.project_id
  name                               = var.name
  router                             = google_compute_router.main.name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}
resource "google_compute_global_address" "private_services" {
  project       = var.project_id
  name          = "${var.name}-private-services"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.main.id
}
resource "google_service_networking_connection" "private_services" {
  network                 = google_compute_network.main.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_services.name]
}

# ---------------------------------------------------------------------------------------------
# GKE (regional, private nodes): Dataplane V2 enforces NetworkPolicy, Workload Identity, Secrets
# encrypted with Cloud KMS, Managed Service for Prometheus, Shielded nodes. The control plane is
# reached through its IAM-authenticated DNS endpoint; the public IP endpoint only admits
# var.master_authorized_cidrs.
# ---------------------------------------------------------------------------------------------
resource "google_service_account" "nodes" {
  project      = var.project_id
  account_id   = "${var.name}-nodes"
  display_name = "GKE nodes (${var.environment})"
}
resource "google_project_iam_member" "nodes" {
  for_each = toset([
    "roles/logging.logWriter", "roles/monitoring.metricWriter", "roles/monitoring.viewer",
    "roles/stackdriver.resourceMetadata.writer", "roles/autoscaling.metricsWriter",
  ])
  project = var.project_id
  role    = each.value
  member  = google_service_account.nodes.member
}
resource "google_artifact_registry_repository_iam_member" "nodes_pull" {
  project    = local.registry.project
  location   = local.registry.location
  repository = local.registry.repository
  role       = "roles/artifactregistry.reader"
  member     = google_service_account.nodes.member
}

resource "google_container_cluster" "main" {
  project             = var.project_id
  name                = var.name
  location            = var.region
  network             = google_compute_network.main.id
  subnetwork          = google_compute_subnetwork.gke.id
  networking_mode     = "VPC_NATIVE"
  datapath_provider   = "ADVANCED_DATAPATH"
  deletion_protection = local.prod

  remove_default_node_pool = true
  initial_node_count       = 1

  release_channel { channel = var.gke_release_channel }
  workload_identity_config { workload_pool = "${var.project_id}.svc.id.goog" }
  ip_allocation_policy {
    cluster_secondary_range_name  = "pods"
    services_secondary_range_name = "services"
  }
  private_cluster_config {
    enable_private_nodes    = true
    enable_private_endpoint = false
    master_ipv4_cidr_block  = var.master_cidr
  }
  control_plane_endpoints_config {
    dns_endpoint_config { allow_external_traffic = true }
  }
  master_authorized_networks_config {
    gcp_public_cidrs_access_enabled = false
    dynamic "cidr_blocks" {
      for_each = var.master_authorized_cidrs
      content { cidr_block = cidr_blocks.value }
    }
  }
  database_encryption {
    state    = "ENCRYPTED"
    key_name = google_kms_crypto_key.data.id
  }
  addons_config {
    http_load_balancing { disabled = false }
    gce_persistent_disk_csi_driver_config { enabled = true }
  }
  logging_config { enable_components = ["SYSTEM_COMPONENTS", "WORKLOADS", "APISERVER"] }
  monitoring_config {
    enable_components = ["SYSTEM_COMPONENTS", "APISERVER", "SCHEDULER", "CONTROLLER_MANAGER"]
    managed_prometheus { enabled = true }
  }
  security_posture_config {
    mode               = "BASIC"
    vulnerability_mode = "VULNERABILITY_BASIC"
  }
  maintenance_policy {
    recurring_window {
      start_time = "2026-01-04T02:00:00Z"
      end_time   = "2026-01-04T06:00:00Z"
      recurrence = "FREQ=WEEKLY;BYDAY=SA,SU"
    }
  }
  resource_labels = local.labels
  depends_on      = [google_kms_crypto_key_iam_member.agents]
}

resource "google_container_node_pool" "general" {
  project  = var.project_id
  name     = "general"
  cluster  = google_container_cluster.main.id
  location = var.region
  autoscaling {
    min_node_count = var.node_min_per_zone
    max_node_count = var.node_max_per_zone
  }
  management {
    auto_repair  = true
    auto_upgrade = true
  }
  upgrade_settings {
    max_surge       = 1
    max_unavailable = 0
  }
  node_config {
    machine_type    = var.node_machine_type
    disk_type       = "pd-balanced"
    disk_size_gb    = 100
    image_type      = "COS_CONTAINERD"
    service_account = google_service_account.nodes.email
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]
    labels          = { workload = "general" }
    resource_labels = local.labels
    workload_metadata_config { mode = "GKE_METADATA" }
    shielded_instance_config {
      enable_secure_boot          = true
      enable_integrity_monitoring = true
    }
  }
}

# ---------------------------------------------------------------------------------------------
# PostgreSQL (Cloud SQL): private IP only, TLS required, CMEK, regional HA, PITR, backups stored
# in a multi-region for disaster recovery.
# ---------------------------------------------------------------------------------------------
resource "random_password" "db" {
  length  = 40
  special = false
}
resource "google_sql_database_instance" "main" {
  project             = var.project_id
  name                = var.name
  region              = var.region
  database_version    = "POSTGRES_16"
  encryption_key_name = google_kms_crypto_key.data.id
  deletion_protection = local.prod
  settings {
    edition               = "ENTERPRISE"
    tier                  = var.db_tier
    availability_type     = var.db_high_availability ? "REGIONAL" : "ZONAL"
    disk_type             = "PD_SSD"
    disk_size             = var.db_disk_size_gb
    disk_autoresize       = true
    disk_autoresize_limit = var.db_disk_size_gb * 5
    user_labels           = local.labels
    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.main.id
      ssl_mode        = "ENCRYPTED_ONLY"
    }
    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      start_time                     = "02:00"
      location                       = var.db_backup_location
      transaction_log_retention_days = 7
      backup_retention_settings { retained_backups = var.db_backup_retention_count }
    }
    maintenance_window {
      day          = 7
      hour         = 3
      update_track = "stable"
    }
    insights_config {
      query_insights_enabled  = true
      record_application_tags = true
    }
    database_flags {
      name  = "log_min_duration_statement"
      value = "1000"
    }
  }
  depends_on = [google_service_networking_connection.private_services, google_kms_crypto_key_iam_member.agents]
}
resource "google_sql_database" "recruiter" {
  project  = var.project_id
  name     = "recruiter"
  instance = google_sql_database_instance.main.name
}
resource "google_sql_user" "recruiter" {
  project  = var.project_id
  name     = "recruiter"
  instance = google_sql_database_instance.main.name
  password = random_password.db.result
}

# ---------------------------------------------------------------------------------------------
# Redis (Memorystore): private services access, AUTH, TLS (server authentication), CMEK,
# HA replica and RDB persistence in production.
# ---------------------------------------------------------------------------------------------
resource "google_redis_instance" "main" {
  project                 = var.project_id
  name                    = var.name
  region                  = var.region
  tier                    = var.redis_tier
  memory_size_gb          = var.redis_memory_gb
  redis_version           = "REDIS_7_2"
  authorized_network      = google_compute_network.main.id
  connect_mode            = "PRIVATE_SERVICE_ACCESS"
  auth_enabled            = true
  transit_encryption_mode = "SERVER_AUTHENTICATION"
  customer_managed_key    = google_kms_crypto_key.data.id
  labels                  = local.labels
  dynamic "persistence_config" {
    for_each = local.prod ? [1] : []
    content {
      persistence_mode    = "RDB"
      rdb_snapshot_period = "TWELVE_HOURS"
    }
  }
  maintenance_policy {
    weekly_maintenance_window {
      day = "SUNDAY"
      start_time {
        hours   = 3
        minutes = 0
      }
    }
  }
  depends_on = [google_service_networking_connection.private_services, google_kms_crypto_key_iam_member.agents]
}

# ---------------------------------------------------------------------------------------------
# Candidate documents (Cloud Storage): private, CMEK, versioned, soft delete, lifecycle.
# Pods access it through Workload Identity; GCS only serves HTTPS.
# ---------------------------------------------------------------------------------------------
resource "google_storage_bucket" "documents" {
  project                     = var.project_id
  name                        = "${var.project_id}-${var.environment}-documents"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = !local.prod
  labels                      = local.labels
  versioning { enabled = true }
  encryption { default_kms_key_name = google_kms_crypto_key.data.id }
  soft_delete_policy { retention_duration_seconds = 7 * 86400 }
  lifecycle_rule {
    condition { days_since_noncurrent_time = var.document_retention_days }
    action { type = "Delete" }
  }
  lifecycle_rule {
    condition { age = 1 }
    action { type = "AbortIncompleteMultipartUpload" }
  }
  depends_on = [google_kms_crypto_key_iam_member.agents]
}
resource "google_storage_bucket_iam_member" "app_documents" {
  bucket = google_storage_bucket.documents.name
  role   = "roles/storage.objectUser"
  member = local.app_principal
}

# ---------------------------------------------------------------------------------------------
# Application secrets, synced into the cluster by External Secrets Operator:
#   <name>-infra  managed by Terraform (connection strings, bucket, JWT secret) — always in sync
#   <name>        managed by operators (DATA_ENCRYPTION_KEY, LLM API keys, SMTP, OIDC); Terraform
#                 creates the container only and never writes versions
# ---------------------------------------------------------------------------------------------
resource "random_password" "jwt" {
  length  = 64
  special = false
}
resource "google_secret_manager_secret" "app" {
  for_each  = toset(["${var.name}-infra", var.name])
  project   = var.project_id
  secret_id = each.value
  labels    = local.labels
  replication {
    user_managed {
      replicas {
        location = var.region
        customer_managed_encryption { kms_key_name = google_kms_crypto_key.data.id }
      }
    }
  }
  depends_on = [google_kms_crypto_key_iam_member.agents]
}
resource "google_secret_manager_secret_version" "infra" {
  secret = google_secret_manager_secret.app["${var.name}-infra"].id
  secret_data = jsonencode({
    DATABASE_URL     = "postgresql+psycopg://recruiter:${random_password.db.result}@${google_sql_database_instance.main.private_ip_address}:5432/recruiter?sslmode=require"
    REDIS_URL        = "rediss://:${google_redis_instance.main.auth_string}@${google_redis_instance.main.host}:${google_redis_instance.main.port}/0"
    REDIS_CA_CERT    = join("\n", [for c in google_redis_instance.main.server_ca_certs : c.cert])
    JWT_SECRET       = random_password.jwt.result
    GCP_PROJECT_ID   = var.project_id
    GCS_BUCKET       = google_storage_bucket.documents.name
    GCS_KMS_KEY_NAME = google_kms_crypto_key.data.id
  })
}
resource "google_secret_manager_secret_iam_member" "eso" {
  for_each  = google_secret_manager_secret.app
  project   = var.project_id
  secret_id = each.value.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = local.eso_principal
}

# ---------------------------------------------------------------------------------------------
# CI/CD: GitHub Actions jobs running in the matching GitHub environment impersonate this service
# account through the bootstrap Workload Identity pool (no keys in GitHub).
# ---------------------------------------------------------------------------------------------
resource "google_service_account" "deploy" {
  project      = var.project_id
  account_id   = "${var.name}-deploy"
  display_name = "GitHub Actions deploy (${var.environment})"
}
resource "google_service_account_iam_member" "deploy_wif" {
  service_account_id = google_service_account.deploy.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${var.github_workload_identity_pool}/attribute.environment/${var.environment}"
}
resource "google_project_iam_custom_role" "deploy" {
  project     = var.project_id
  role_id     = "${replace(var.name, "-", "_")}_deploy"
  title       = "${var.name} deploy extras"
  description = "On-demand Cloud SQL backup before production releases"
  permissions = ["cloudsql.backupRuns.create", "cloudsql.backupRuns.get", "cloudsql.instances.get"]
}
resource "google_project_iam_member" "deploy" {
  for_each = {
    gke    = "roles/container.developer"
    backup = google_project_iam_custom_role.deploy.id
  }
  project = var.project_id
  role    = each.value
  member  = google_service_account.deploy.member
}
resource "google_artifact_registry_repository_iam_member" "deploy_push" {
  count      = var.push_images ? 1 : 0
  project    = local.registry.project
  location   = local.registry.location
  repository = local.registry.repository
  role       = "roles/artifactregistry.writer"
  member     = google_service_account.deploy.member
}

# ---------------------------------------------------------------------------------------------
# Edge: global static IP, TLS policy and Cloud Armor (OWASP rules, per-IP rate limiting,
# adaptive DDoS protection). Referenced by name from the Helm chart's GKE Ingress resources.
# ---------------------------------------------------------------------------------------------
resource "google_compute_global_address" "ingress" {
  project    = var.project_id
  name       = "${var.name}-ingress"
  depends_on = [google_project_service.apis]
}
resource "google_compute_ssl_policy" "tls" {
  project         = var.project_id
  name            = "${var.name}-tls"
  profile         = "MODERN"
  min_tls_version = "TLS_1_2"
  depends_on      = [google_project_service.apis]
}
resource "google_compute_security_policy" "edge" {
  project     = var.project_id
  name        = "${var.name}-edge"
  description = "WAF and rate limiting for ${var.name}"

  dynamic "rule" {
    for_each = {
      1000 = "sqli-v33-stable"
      1001 = "xss-v33-stable"
      1002 = "lfi-v33-stable"
      1003 = "rce-v33-stable"
      1004 = "rfi-v33-stable"
      1005 = "scannerdetection-v33-stable"
      1006 = "protocolattack-v33-stable"
      1007 = "sessionfixation-v33-stable"
    }
    content {
      priority    = rule.key
      action      = "deny(403)"
      preview     = var.waf_preview
      description = "OWASP CRS ${rule.value}"
      match {
        expr { expression = "evaluatePreconfiguredWaf('${rule.value}', {'sensitivity': 1})" }
      }
    }
  }
  rule {
    priority    = 2000
    action      = "rate_based_ban"
    description = "Per-IP rate limit (2000 requests / 5 min, 10 min ban)"
    match {
      versioned_expr = "SRC_IPS_V1"
      config { src_ip_ranges = ["*"] }
    }
    rate_limit_options {
      conform_action   = "allow"
      exceed_action    = "deny(429)"
      enforce_on_key   = "IP"
      ban_duration_sec = 600
      rate_limit_threshold {
        count        = 2000
        interval_sec = 300
      }
    }
  }
  rule {
    priority    = 2147483647
    action      = "allow"
    description = "Default allow"
    match {
      versioned_expr = "SRC_IPS_V1"
      config { src_ip_ranges = ["*"] }
    }
  }
  adaptive_protection_config {
    layer_7_ddos_defense_config { enable = true }
  }
  depends_on = [google_project_service.apis]
}

# ---------------------------------------------------------------------------------------------
# Alerts on managed services (application SLO alerts live in the Helm chart as Prometheus rules)
# ---------------------------------------------------------------------------------------------
resource "google_monitoring_notification_channel" "email" {
  count        = var.alert_email == "" ? 0 : 1
  project      = var.project_id
  display_name = "${var.name} alerts"
  type         = "email"
  labels       = { email_address = var.alert_email }
}
resource "google_monitoring_alert_policy" "managed" {
  for_each = {
    db-cpu       = { filter = "metric.type=\"cloudsql.googleapis.com/database/cpu/utilization\" AND resource.type=\"cloudsql_database\" AND resource.label.database_id=\"${var.project_id}:${google_sql_database_instance.main.name}\"", threshold = 0.8, aligner = "ALIGN_MEAN" }
    db-disk      = { filter = "metric.type=\"cloudsql.googleapis.com/database/disk/utilization\" AND resource.type=\"cloudsql_database\" AND resource.label.database_id=\"${var.project_id}:${google_sql_database_instance.main.name}\"", threshold = 0.85, aligner = "ALIGN_MAX" }
    redis-memory = { filter = "metric.type=\"redis.googleapis.com/stats/memory/usage_ratio\" AND resource.type=\"redis_instance\" AND resource.label.instance_id=\"${google_redis_instance.main.id}\"", threshold = 0.8, aligner = "ALIGN_MEAN" }
  }
  project               = var.project_id
  display_name          = "${var.name} ${each.key}"
  combiner              = "OR"
  notification_channels = google_monitoring_notification_channel.email[*].id
  conditions {
    display_name = "${each.key} above ${each.value.threshold * 100}%"
    condition_threshold {
      filter          = each.value.filter
      comparison      = "COMPARISON_GT"
      threshold_value = each.value.threshold
      duration        = "900s"
      aggregations {
        alignment_period   = "300s"
        per_series_aligner = each.value.aligner
      }
    }
  }
  depends_on = [google_project_service.apis]
}
