output "project_id" { value = var.project_id }
output "region" { value = var.region }
output "cluster_name" { value = google_container_cluster.main.name }
output "deploy_service_account" {
  description = "GitHub environment variable GCP_DEPLOY_SERVICE_ACCOUNT"
  value       = google_service_account.deploy.email
}
output "documents_bucket" { value = google_storage_bucket.documents.name }
output "sql_instance" { value = google_sql_database_instance.main.name }
output "secrets" {
  description = "Secret Manager secrets synced by External Secrets (infra: Terraform-managed; app: operator-managed)"
  value       = { infra = google_secret_manager_secret.app["${var.name}-infra"].secret_id, app = google_secret_manager_secret.app[var.name].secret_id }
}
output "ingress_ip" {
  description = "Point the environment's DNS A record here"
  value       = google_compute_global_address.ingress.address
}
output "ingress_ip_name" { value = google_compute_global_address.ingress.name }
output "ssl_policy_name" { value = google_compute_ssl_policy.tls.name }
output "security_policy_name" { value = google_compute_security_policy.edge.name }
output "kms_key" { value = google_kms_crypto_key.data.id }
