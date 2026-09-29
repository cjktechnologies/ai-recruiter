# Deployment Guide

## Environments

| Env | Where | How it's deployed |
|---|---|---|
| Local | Docker Compose | `cp .env.example .env && docker compose up --build` |
| Staging | AWS (EKS, eu-west-1) | Automatically on every push to `main` (CD workflow) |
| Production | AWS (EKS, eu-west-1; DR backups in eu-central-1) | Same image as staging, after approval in the GitHub `production` environment |

## 1. One-time AWS setup

```bash
# Remote state + GitHub OIDC provider
terraform -chdir=infra/terraform/bootstrap init && terraform -chdir=infra/terraform/bootstrap apply

# Platform per environment (VPC, EKS, RDS, Redis, S3, KMS, ECR, WAF, Secrets Manager, IAM)
terraform -chdir=infra/terraform/environments/staging init
terraform -chdir=infra/terraform/environments/staging apply
# repeat for production
```

Then, per cluster:

1. Install cluster add-ons: AWS Load Balancer Controller, External Secrets Operator (with a `ClusterSecretStore` named
   `aws-secrets-manager`), kube-prometheus-stack and a log shipper (e.g. Fluent Bit → CloudWatch/OpenSearch).
2. Add the non-infrastructure secrets to `ai-recruiter/<env>` in Secrets Manager: `DATA_ENCRYPTION_KEY` (Fernet key),
   `ANTHROPIC_API_KEY` (or other provider keys), `SMTP_HOST/USERNAME/PASSWORD`, `OIDC_ISSUER/CLIENT_ID/CLIENT_SECRET`.
3. Associate the WAF ACL (`waf_acl_arn` output) with the ALB. Add the annotation
   `alb.ingress.kubernetes.io/wafv2-acl-arn` via Helm values.
4. In GitHub, create the `staging` and `production` environments (require reviewers on production) and set these
   variables: `AWS_DEPLOY_ROLE_ARN`, `APP_ROLE_ARN`, `TLS_CERT_ARN`, `PUBLIC_URL`.

## 2. Continuous delivery

`.github/workflows/cd.yml`:

1. Build `api` and `web` images (SBOM + provenance), push to ECR with the git SHA as an immutable tag.
2. Deploy to staging with `helm upgrade --install --atomic`. **Migrations run first** as a `pre-upgrade` hook Job; if
   they fail, the release is not applied.
3. Smoke tests (`/login` through the ALB, `/readyz` in-cluster). Any failure triggers `helm rollback`.
4. Production waits for approval, takes an RDS snapshot, then runs the same steps.

## 3. Database migration pipeline

- Migrations are Alembic revisions in `backend/alembic/versions`. CI proves each one applies, downgrades and leaves no
  drift against the models (`alembic check`).
- **Expand/contract rule:** releases must be compatible with the previous schema. Additive changes go in release N;
  destructive changes (drop or rename) go in N+1 once no code references the old shape. This makes app rollback safe
  without schema rollback.
- Long-running data migrations run as Celery tasks, not in Alembic.

## 4. Rollback procedure

| Situation | Action |
|---|---|
| Failed rollout / smoke test | Automatic (`--atomic` / `helm rollback`) |
| Bad release discovered later | Run the CD workflow manually with `image_tag=<previous sha>` (or `helm rollback ai-recruiter <rev> -n ai-recruiter`) |
| Bad migration (additive) | Roll the app back; leave the schema (expand/contract guarantees compatibility); fix forward |
| Data corruption | Restore RDS to a point in time before the incident into a new instance, verify, switch `DATABASE_URL` (see runbook) |
| AI misbehaviour | Set `LLM_PROVIDER=local` in the ConfigMap/values and redeploy config. The deterministic path continues with no downtime |

## 5. Configuration reference

All settings are environment variables (`backend/app/core/config.py`). Outside local/test, production guards refuse to
start with default `JWT_SECRET` or `DATA_ENCRYPTION_KEY`. Key variables: `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`,
`DATA_ENCRYPTION_KEY`, `LLM_PROVIDER`, `LLM_MODEL`, `LLM_EFFORT`, `STORAGE_BACKEND`, `S3_BUCKET`, `S3_KMS_KEY_ID`,
`CLAMAV_HOST`, `REQUIRE_MALWARE_SCAN`, `EMAIL_BACKEND`, `SMTP_*`, `SMS_BACKEND`, `TWILIO_*`, `OIDC_*`,
`CORS_ORIGINS`, `PUBLIC_BASE_URL`, `RATE_LIMIT_PER_MINUTE`, `AUTH_RATE_LIMIT_PER_MINUTE`, `MAX_UPLOAD_MB`.
