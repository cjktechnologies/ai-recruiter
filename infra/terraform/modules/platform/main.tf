data "aws_availability_zones" "available" { state = "available" }
data "aws_caller_identity" "current" {}

locals {
  azs  = length(var.azs) > 0 ? var.azs : slice(data.aws_availability_zones.available.names, 0, 3)
  tags = merge(var.tags, { Application = "ai-recruiter", Environment = var.environment, ManagedBy = "terraform" })
  prod = var.environment == "production"
}

# ---------------------------------------------------------------------------------------------
# Encryption keys (separate CMKs per data class; automatic rotation)
# ---------------------------------------------------------------------------------------------
resource "aws_kms_key" "data" {
  description             = "${var.name} data at rest (RDS, ElastiCache, S3, Secrets)"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  tags                    = local.tags
}
resource "aws_kms_alias" "data" {
  name          = "alias/${var.name}-data"
  target_key_id = aws_kms_key.data.key_id
}

# ---------------------------------------------------------------------------------------------
# Network: 3-AZ VPC, private subnets for workloads & data, NAT per AZ in production
# ---------------------------------------------------------------------------------------------
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.13"

  name                 = var.name
  cidr                 = var.vpc_cidr
  azs                  = local.azs
  private_subnets      = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 4, i)]
  public_subnets       = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 8, 100 + i)]
  database_subnets     = [for i, _ in local.azs : cidrsubnet(var.vpc_cidr, 8, 110 + i)]
  enable_nat_gateway   = true
  single_nat_gateway   = !local.prod
  enable_dns_hostnames = true

  enable_flow_log                                 = true
  create_flow_log_cloudwatch_log_group            = true
  create_flow_log_cloudwatch_iam_role             = true
  flow_log_cloudwatch_log_group_retention_in_days = 90

  public_subnet_tags  = { "kubernetes.io/role/elb" = 1 }
  private_subnet_tags = { "kubernetes.io/role/internal-elb" = 1 }
  tags                = local.tags
}

# ---------------------------------------------------------------------------------------------
# Kubernetes (EKS) with managed node group, IRSA and add-ons
# ---------------------------------------------------------------------------------------------
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.24"

  cluster_name                    = var.name
  cluster_version                 = var.eks_version
  vpc_id                          = module.vpc.vpc_id
  subnet_ids                      = module.vpc.private_subnets
  cluster_endpoint_public_access  = true
  enable_irsa                     = true
  enable_cluster_creator_admin_permissions = true
  cluster_encryption_config       = { resources = ["secrets"], provider_key_arn = aws_kms_key.data.arn }
  cluster_enabled_log_types       = ["api", "audit", "authenticator"]

  cluster_addons = {
    coredns                = {}
    kube-proxy             = {}
    vpc-cni                = { before_compute = true, configuration_values = jsonencode({ enableNetworkPolicy = "true" }) }
    eks-pod-identity-agent = {}
    aws-ebs-csi-driver     = {}
  }

  eks_managed_node_groups = {
    general = {
      ami_type       = "AL2023_ARM_64_STANDARD"
      instance_types = var.node_instance_types
      min_size       = var.node_min
      max_size       = var.node_max
      desired_size   = var.node_min
      labels         = { workload = "general" }
    }
  }
  tags = local.tags
}

# ---------------------------------------------------------------------------------------------
# PostgreSQL (RDS): encrypted, Multi-AZ, PITR backups, TLS enforced, Performance Insights
# ---------------------------------------------------------------------------------------------
resource "aws_security_group" "db" {
  name        = "${var.name}-db"
  description = "PostgreSQL from EKS nodes only"
  vpc_id      = module.vpc.vpc_id
  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [module.eks.node_security_group_id]
  }
  tags = local.tags
}

resource "aws_db_parameter_group" "pg" {
  name   = "${var.name}-pg16"
  family = "postgres16"
  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }
  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }
  tags = local.tags
}

resource "random_password" "db" {
  length  = 40
  special = false
}

resource "aws_db_instance" "main" {
  identifier                            = var.name
  engine                                = "postgres"
  engine_version                        = "16.4"
  instance_class                        = var.db_instance_class
  allocated_storage                     = var.db_allocated_storage
  max_allocated_storage                 = var.db_allocated_storage * 5
  storage_type                          = "gp3"
  storage_encrypted                     = true
  kms_key_id                            = aws_kms_key.data.arn
  db_name                               = "recruiter"
  username                              = "recruiter"
  password                              = random_password.db.result
  db_subnet_group_name                  = module.vpc.database_subnet_group_name
  vpc_security_group_ids                = [aws_security_group.db.id]
  parameter_group_name                  = aws_db_parameter_group.pg.name
  multi_az                              = var.db_multi_az
  backup_retention_period               = var.db_backup_retention_days
  backup_window                         = "02:00-03:00"
  maintenance_window                    = "sun:03:30-sun:04:30"
  copy_tags_to_snapshot                 = true
  deletion_protection                   = local.prod
  skip_final_snapshot                   = !local.prod
  final_snapshot_identifier             = "${var.name}-final"
  performance_insights_enabled          = true
  performance_insights_kms_key_id       = aws_kms_key.data.arn
  enabled_cloudwatch_logs_exports       = ["postgresql"]
  auto_minor_version_upgrade            = true
  iam_database_authentication_enabled   = true
  tags                                  = local.tags
}

# Cross-region snapshot copies for disaster recovery (production).
resource "aws_db_instance_automated_backups_replication" "dr" {
  count                  = local.prod ? 1 : 0
  provider               = aws.dr
  source_db_instance_arn = aws_db_instance.main.arn
  kms_key_id             = aws_kms_key.dr[0].arn
  retention_period       = 14
}
resource "aws_kms_key" "dr" {
  count               = local.prod ? 1 : 0
  provider            = aws.dr
  description         = "${var.name} DR backups"
  enable_key_rotation = true
}

# ---------------------------------------------------------------------------------------------
# Redis (ElastiCache): encryption in transit/at rest, AUTH token, automatic failover
# ---------------------------------------------------------------------------------------------
resource "aws_security_group" "redis" {
  name   = "${var.name}-redis"
  vpc_id = module.vpc.vpc_id
  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [module.eks.node_security_group_id]
  }
  tags = local.tags
}
resource "aws_elasticache_subnet_group" "redis" {
  name       = var.name
  subnet_ids = module.vpc.private_subnets
}
resource "random_password" "redis" {
  length  = 48
  special = false
}
resource "aws_elasticache_replication_group" "redis" {
  replication_group_id       = var.name
  description                = "${var.name} cache, broker and rate limiting"
  engine                     = "redis"
  engine_version             = "7.1"
  node_type                  = var.redis_node_type
  num_cache_clusters         = local.prod ? 2 : 1
  automatic_failover_enabled = local.prod
  multi_az_enabled           = local.prod
  subnet_group_name          = aws_elasticache_subnet_group.redis.name
  security_group_ids         = [aws_security_group.redis.id]
  at_rest_encryption_enabled = true
  kms_key_id                 = aws_kms_key.data.arn
  transit_encryption_enabled = true
  auth_token                 = random_password.redis.result
  snapshot_retention_limit   = 7
  tags                       = local.tags
}

# ---------------------------------------------------------------------------------------------
# Candidate documents (S3): private, KMS-encrypted, versioned, TLS-only, lifecycle
# ---------------------------------------------------------------------------------------------
resource "aws_s3_bucket" "documents" {
  bucket = "${var.name}-documents-${data.aws_caller_identity.current.account_id}"
  tags   = local.tags
}
resource "aws_s3_bucket_public_access_block" "documents" {
  bucket                  = aws_s3_bucket.documents.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_ownership_controls" "documents" {
  bucket = aws_s3_bucket.documents.id
  rule { object_ownership = "BucketOwnerEnforced" }
}
resource "aws_s3_bucket_versioning" "documents" {
  bucket = aws_s3_bucket.documents.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.data.arn
    }
    bucket_key_enabled = true
  }
}
resource "aws_s3_bucket_lifecycle_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id
  rule {
    id     = "purge-deleted-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration { noncurrent_days = var.document_retention_days }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
}
resource "aws_s3_bucket_policy" "documents" {
  bucket = aws_s3_bucket.documents.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.documents.arn, "${aws_s3_bucket.documents.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

# ---------------------------------------------------------------------------------------------
# Container registry
# ---------------------------------------------------------------------------------------------
resource "aws_ecr_repository" "repo" {
  for_each             = toset(["api", "web"])
  name                 = "ai-recruiter-${each.key}"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.data.arn
  }
  tags = local.tags
}
resource "aws_ecr_lifecycle_policy" "repo" {
  for_each   = aws_ecr_repository.repo
  repository = each.value.name
  policy = jsonencode({ rules = [{
    rulePriority = 1, description = "keep last 100 images",
    selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 100 },
    action       = { type = "expire" }
  }] })
}

# ---------------------------------------------------------------------------------------------
# Application secrets (synced into the cluster by External Secrets Operator)
# ---------------------------------------------------------------------------------------------
resource "random_password" "jwt" {
  length  = 64
  special = false
}
resource "aws_secretsmanager_secret" "app" {
  name       = "ai-recruiter/${var.environment}"
  kms_key_id = aws_kms_key.data.arn
  tags       = local.tags
}
# Infrastructure-derived values are written here; third-party credentials (LLM API keys, SMTP,
# OIDC client secret, DATA_ENCRYPTION_KEY) are added out-of-band and are ignored by Terraform.
resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    DATABASE_URL  = "postgresql+psycopg://recruiter:${random_password.db.result}@${aws_db_instance.main.address}:5432/recruiter?sslmode=require"
    REDIS_URL     = "rediss://:${random_password.redis.result}@${aws_elasticache_replication_group.redis.primary_endpoint_address}:6379/0"
    JWT_SECRET    = random_password.jwt.result
    S3_BUCKET     = aws_s3_bucket.documents.bucket
    S3_KMS_KEY_ID = aws_kms_key.data.arn
  })
  lifecycle { ignore_changes = [secret_string] }
}

# ---------------------------------------------------------------------------------------------
# Workload identity (IRSA): least-privilege S3 + KMS for the application pods
# ---------------------------------------------------------------------------------------------
module "app_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.44"

  role_name = "${var.name}-app"
  oidc_providers = {
    main = {
      provider_arn               = module.eks.oidc_provider_arn
      namespace_service_accounts = ["ai-recruiter:ai-recruiter"]
    }
  }
  role_policy_arns = { app = aws_iam_policy.app.arn }
}
resource "aws_iam_policy" "app" {
  name = "${var.name}-app"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
        Resource = "${aws_s3_bucket.documents.arn}/*" },
      { Effect = "Allow", Action = ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey"],
        Resource = aws_kms_key.data.arn },
    ]
  })
}

# ---------------------------------------------------------------------------------------------
# CI/CD: GitHub Actions deploys via OIDC (no long-lived AWS keys in GitHub)
# ---------------------------------------------------------------------------------------------
data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}
resource "aws_iam_role" "deploy" {
  name = "${var.name}-github-deploy"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = data.aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com" }
        StringLike   = { "token.actions.githubusercontent.com:sub" = "repo:${var.github_repository}:environment:${var.environment}" }
      }
    }]
  })
  tags = local.tags
}
resource "aws_iam_role_policy" "deploy" {
  role = aws_iam_role.deploy.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
      { Effect = "Allow", Action = ["ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage", "ecr:DescribeImages"],
        Resource = [for r in aws_ecr_repository.repo : r.arn] },
      { Effect = "Allow", Action = ["eks:DescribeCluster"], Resource = module.eks.cluster_arn },
      { Effect = "Allow", Action = ["kms:Decrypt", "kms:GenerateDataKey"], Resource = aws_kms_key.data.arn },
    ]
  })
}
resource "aws_eks_access_entry" "deploy" {
  cluster_name  = module.eks.cluster_name
  principal_arn = aws_iam_role.deploy.arn
}
resource "aws_eks_access_policy_association" "deploy" {
  cluster_name  = module.eks.cluster_name
  principal_arn = aws_iam_role.deploy.arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSEditPolicy"
  access_scope {
    type       = "namespace"
    namespaces = ["ai-recruiter"]
  }
}

# ---------------------------------------------------------------------------------------------
# Edge protection: WAF (managed rules + rate limit) for the public load balancer
# ---------------------------------------------------------------------------------------------
resource "aws_wafv2_web_acl" "main" {
  name  = var.name
  scope = "REGIONAL"
  default_action {
    allow {}
  }
  dynamic "rule" {
    for_each = { AWSManagedRulesCommonRuleSet = 1, AWSManagedRulesKnownBadInputsRuleSet = 2, AWSManagedRulesSQLiRuleSet = 3 }
    content {
      name     = rule.key
      priority = rule.value
      override_action {
        none {}
      }
      statement {
        managed_rule_group_statement {
          vendor_name = "AWS"
          name        = rule.key
        }
      }
      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = rule.key
        sampled_requests_enabled   = true
      }
    }
  }
  rule {
    name     = "rate-limit-per-ip"
    priority = 10
    action {
      block {}
    }
    statement {
      rate_based_statement {
        limit              = 2000
        aggregate_key_type = "IP"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "rate-limit"
      sampled_requests_enabled   = true
    }
  }
  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = var.name
    sampled_requests_enabled   = true
  }
  tags = local.tags
}

# ---------------------------------------------------------------------------------------------
# Alarms on managed services
# ---------------------------------------------------------------------------------------------
resource "aws_sns_topic" "alerts" {
  name              = "${var.name}-alerts"
  kms_master_key_id = aws_kms_key.data.id
}
resource "aws_cloudwatch_metric_alarm" "db_cpu" {
  alarm_name          = "${var.name}-db-cpu"
  namespace           = "AWS/RDS"
  metric_name         = "CPUUtilization"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.main.identifier }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
resource "aws_cloudwatch_metric_alarm" "db_storage" {
  alarm_name          = "${var.name}-db-free-storage"
  namespace           = "AWS/RDS"
  metric_name         = "FreeStorageSpace"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.main.identifier }
  statistic           = "Minimum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 10737418240
  comparison_operator = "LessThanThreshold"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
resource "aws_cloudwatch_metric_alarm" "redis_memory" {
  alarm_name          = "${var.name}-redis-memory"
  namespace           = "AWS/ElastiCache"
  metric_name         = "DatabaseMemoryUsagePercentage"
  dimensions          = { ReplicationGroupId = aws_elasticache_replication_group.redis.id }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
