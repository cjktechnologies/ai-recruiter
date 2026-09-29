output "cluster_name" { value = module.eks.cluster_name }
output "ecr_repositories" { value = { for k, r in aws_ecr_repository.repo : k => r.repository_url } }
output "documents_bucket" { value = aws_s3_bucket.documents.bucket }
output "app_role_arn" { value = module.app_irsa.iam_role_arn }
output "deploy_role_arn" { value = aws_iam_role.deploy.arn }
output "secrets_manager_secret" { value = aws_secretsmanager_secret.app.name }
output "waf_acl_arn" { value = aws_wafv2_web_acl.main.arn }
output "alerts_topic_arn" { value = aws_sns_topic.alerts.arn }
output "db_endpoint" {
  value     = aws_db_instance.main.address
  sensitive = true
}
