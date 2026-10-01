# Deployment Guide

## Environments

| Env | Where | How it's deployed |
|---|---|---|
| Local | Docker Compose (PostgreSQL, Redis, Cloud Storage emulator, Mailpit) | `cp .env.example .env && docker compose up --build` |
| Staging | Google Cloud (GKE, `europe-west1`) | Automatically on every push to `main` (CD workflow) |
| Production | Google Cloud (GKE, `europe-west1`; database backups in the `eu` multi-region) | Same image as staging, after approval in the GitHub `production` environment |

Use one Google Cloud project per environment (for example `my-recruiter-staging` and `my-recruiter-production`)
plus a shared project for Terraform state, container images and the GitHub identity pool. A single project for
everything also works because resource names are prefixed per environment.

### What runs where

| Concern | Google Cloud service |
|---|---|
| Containers | GKE Standard (regional, private nodes, Dataplane V2 network policy, Workload Identity, Shielded nodes) |
| PostgreSQL | Cloud SQL for PostgreSQL 16 (private IP, TLS only, regional HA in production, PITR) |
| Redis (cache, Celery broker, rate limits) | Memorystore for Redis 7.2 (AUTH + TLS, HA in production) |
| Candidate documents | Cloud Storage (uniform access, public access prevention, versioning, soft delete) |
| Images | Artifact Registry (immutable tags, vulnerability scanning) |
| Secrets | Secret Manager, synced into the cluster by External Secrets Operator |
| Encryption at rest | Cloud KMS customer-managed key per environment (90-day rotation) |
| Edge | Global external Application Load Balancer (GKE Ingress), Google-managed certificate, TLS 1.2+ policy, Cloud Armor (OWASP rules, per-IP rate limiting, adaptive DDoS protection) |
| Metrics, logs, alerts | Managed Service for Prometheus, Cloud Logging, Cloud Monitoring alert policies |
| CI/CD identity | Workload Identity Federation for GitHub Actions (no service-account keys) |

## 1. One-time Google Cloud setup

Run these as a project owner, with `gcloud auth application-default login`.

```bash
# Shared project: Terraform state, Artifact Registry, GitHub Workload Identity Federation pool
terraform -chdir=infra/terraform/bootstrap init
terraform -chdir=infra/terraform/bootstrap apply -var project_id=my-recruiter-shared
terraform -chdir=infra/terraform/bootstrap output        # values used below

# Platform per environment (VPC, GKE, Cloud SQL, Memorystore, Cloud Storage, KMS, Secret Manager,
# Cloud Armor, alerting, deploy identity)
cp infra/terraform/environments/staging/terraform.tfvars.example infra/terraform/environments/staging/terraform.tfvars
# edit terraform.tfvars: project_id, github_workload_identity_pool, artifact_registry_repository, alert_email
terraform -chdir=infra/terraform/environments/staging init -backend-config="bucket=<state_bucket output>"
terraform -chdir=infra/terraform/environments/staging apply
terraform -chdir=infra/terraform/environments/staging output platform
# repeat for production
```

Then, per environment:

1. **DNS.** Point the environment's hostname (an `A` record) at the `ingress_ip` output. The Google-managed
   certificate is issued once DNS resolves to the load balancer, which usually takes 15–60 minutes after the first
   deploy.
2. **Cluster add-on.** Install External Secrets Operator and the `ClusterSecretStore`:
   ```bash
   gcloud container clusters get-credentials ai-recruiter-staging --region europe-west1 --project <project> --dns-endpoint
   helm repo add external-secrets https://charts.external-secrets.io
   helm upgrade --install external-secrets external-secrets/external-secrets -n external-secrets --create-namespace
   sed 's/PROJECT_ID/<project>/' deploy/cluster/cluster-secret-store.yaml | kubectl apply -f -
   ```
   Terraform already granted that operator's Kubernetes service account access to the environment's secrets
   through Workload Identity. Ingress, managed certificates, Cloud Armor and Prometheus collection are built into
   GKE, so nothing else needs installing.
3. **Application secrets.** Terraform writes the infrastructure values to `ai-recruiter-<env>-infra`. Add the
   operator-managed values as a JSON version of `ai-recruiter-<env>` (required before the first deploy):
   ```bash
   python - <<'PY' > /tmp/app-secret.json
   import json
   from cryptography.fernet import Fernet
   print(json.dumps({
       "DATA_ENCRYPTION_KEY": Fernet.generate_key().decode(),
       "ANTHROPIC_API_KEY": "<key>",
       "SMTP_HOST": "<host>", "SMTP_USERNAME": "<user>", "SMTP_PASSWORD": "<password>",
       # optional SSO: "OIDC_ISSUER": "...", "OIDC_CLIENT_ID": "...", "OIDC_CLIENT_SECRET": "..."
   }))
   PY
   gcloud secrets versions add ai-recruiter-staging --project <project> --data-file /tmp/app-secret.json && rm /tmp/app-secret.json
   ```
   Keep `DATA_ENCRYPTION_KEY` stable: it decrypts PII already stored in the database.
4. **Alerting.** Prometheus alert rules from the Helm chart are evaluated by Managed Service for Prometheus; to
   route them, configure the managed Alertmanager (`kubectl -n gmp-public edit secret alertmanager`). Cloud SQL and
   Memorystore alerts go to `alert_email`.
5. **GitHub.** Create the `staging` and `production` environments and **require reviewers on `production`**
   (otherwise production deploys right after staging). Set these variables:

   | Variable | Scope | Value |
   |---|---|---|
   | `GCP_WORKLOAD_IDENTITY_PROVIDER` | repository | bootstrap output `workload_identity_provider` |
   | `GCP_IMAGE_REGISTRY` | repository | bootstrap output `image_registry` |
   | `GCP_REGION` | repository (optional) | defaults to `europe-west1` |
   | `GCP_PROJECT_ID` | each environment | the environment's project |
   | `GCP_DEPLOY_SERVICE_ACCOUNT` | each environment | output `deploy_service_account` |
   | `PUBLIC_URL` | each environment | e.g. `https://recruit.staging.example.com` |

   Only jobs that run in a GitHub environment from this repository can use that environment's deploy service
   account; nothing is stored as a secret.

## 2. Continuous delivery

`.github/workflows/cd.yml`:

1. Build `api` and `web` images (linux/amd64, SBOM + provenance), push to Artifact Registry with the git SHA as an
   immutable tag. Staging and production deploy the same image.
2. Deploy to staging with `helm upgrade --install --atomic`. **Migrations run first** as a `pre-upgrade` hook Job; if
   they fail, the release is not applied. The workflow reaches the cluster through its IAM-authenticated DNS
   endpoint.
3. Smoke tests: `/readyz` and `/login` in the cluster, then `/login` through the load balancer once the managed
   certificate is active. A failed smoke test triggers `helm rollback`.
4. Production waits for approval, takes an on-demand Cloud SQL backup, then runs the same steps.

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
| Data corruption | Clone Cloud SQL to a point in time before the incident, verify, switch `DATABASE_URL` (see runbook) |
| AI misbehaviour | Set `LLM_PROVIDER=local` in the ConfigMap/values and redeploy config. The deterministic path continues with no downtime |

## 5. Configuration reference

All settings are environment variables (`backend/app/core/config.py`). Outside local/test, production guards refuse to
start with default `JWT_SECRET` or `DATA_ENCRYPTION_KEY`. Key variables: `DATABASE_URL`, `REDIS_URL`, `REDIS_TLS_CA_CERT`,
`JWT_SECRET`, `DATA_ENCRYPTION_KEY`, `LLM_PROVIDER`, `LLM_MODEL`, `LLM_EFFORT`, `STORAGE_BACKEND`, `GCP_PROJECT_ID`,
`GCS_BUCKET`, `GCS_KMS_KEY_NAME`, `CLAMAV_HOST`, `REQUIRE_MALWARE_SCAN`, `EMAIL_BACKEND`, `SMTP_*`, `SMS_BACKEND`, `TWILIO_*`, `OIDC_*`,
`CORS_ORIGINS`, `PUBLIC_BASE_URL`, `RATE_LIMIT_PER_MINUTE`, `AUTH_RATE_LIMIT_PER_MINUTE`, `MAX_UPLOAD_MB`.
