# Operations Runbook: Monitoring, Alerting, Backup & DR

## Observability design

| Signal | Source | Where |
|---|---|---|
| Metrics | `/metrics` (Prometheus): `http_requests_total{method,route,status}`, `http_request_duration_seconds` histogram; Celery via flower/exporter; Cloud SQL and Memorystore system metrics | Managed Service for Prometheus, Cloud Monitoring (Grafana optional) |
| Logs | Structured JSON to stdout with `request_id`, `org_id`, `user_id`; PII and secrets redacted at the formatter | Cloud Logging (collected by GKE; load-balancer request logs enabled) |
| Traces | Correlated by `X-Request-ID` (propagated from the web BFF); OpenTelemetry instrumentation can be enabled with `opentelemetry-instrument` without code changes | OTLP collector → Cloud Trace |
| AI telemetry | `ai_agent_executions` (latency, tokens, provider, model, prompt version, flags) | AI agents page, SQL |
| Business SLOs | Funnel, SLA breaches, fairness alerts | Analytics page |
| Health | `/healthz` (liveness), `/readyz` (DB + Redis) | Kubernetes probes, load-balancer health checks (`BackendConfig`) |

### SLOs

- Availability 99.9%: error budget 43 min/month (5xx ratio).
- Latency: p95 < 300 ms reads, < 800 ms writes.

## Alerts (Prometheus rules + Cloud Monitoring)

| Alert | Severity | First response |
|---|---|---|
| <a id="api-errors"></a>APIHighErrorRate (>2% 5xx, 10 min) | critical | Check the latest deploy (`helm history`); roll back if correlated. Inspect logs by `request_id`; check Cloud SQL/Memorystore health |
| <a id="latency"></a>APIHighLatency (p95 > 1 s) | warning | Cloud SQL Query Insights top queries; HPA saturation; LLM provider latency (AI agents page) |
| <a id="api-down"></a>APIDown | critical | `kubectl get pods -n ai-recruiter`; readiness failures usually mean DB or Redis; check the External Secrets sync |
| <a id="auth"></a>AuthFailureSpike | warning | Possible credential stuffing: confirm the Cloud Armor rate rule is banning; lockouts are automatic; consider tightening Cloud Armor |
| <a id="abuse"></a>RateLimitingSpike | warning | Identify the IP or tenant; Cloud Armor deny rule if malicious; contact the tenant if it's an integration misconfiguration |
| db-cpu / db-disk / redis-memory (Cloud Monitoring → `alert_email`) | warning | Scale the Cloud SQL tier or Memorystore size (disk autoresizes up to 5×); review slow queries |
| Cloud Armor WAF blocks on legitimate traffic (403 in load-balancer logs, `enforcedSecurityPolicy`) | warning | Identify the rule from the log entry; tune with `waf_preview = true` or a rule exclusion, then re-enforce |

## Backup strategy

| Data | Mechanism | Retention | RPO |
|---|---|---|---|
| PostgreSQL | Cloud SQL automated daily backups + PITR (transaction logs 7 days) | 30 backups (prod) | ≤ 5 min |
| PostgreSQL (DR) | Backups stored in the `eu` multi-region (survive a regional outage) | 30 backups | ≤ 24 h (latest backup) |
| PostgreSQL (release) | On-demand backup before each production deploy | Until deleted (prune after 90 days) | n/a |
| Documents (Cloud Storage) | Versioning + 7-day soft delete; noncurrent versions expire after `document_retention_days` | 30 days | 0 |
| Redis | RDB snapshots every 12 h in production. Redis holds only rebuildable state: queues, rate limits, results | n/a | n/a |
| Configuration | Git (Helm, Terraform) + Secret Manager versions | ∞ | 0 |

**Restore drills run quarterly**: restore the latest PITR into staging, run migrations and the smoke suite, and record
the achieved RTO.

## Disaster recovery

| Scenario | Procedure | RTO |
|---|---|---|
| Zone failure | Automatic: Cloud SQL regional HA failover, Memorystore Standard-tier failover, regional GKE reschedules pods across zones | Minutes |
| Accidental data change | `gcloud sql instances clone ai-recruiter-production ai-recruiter-production-restore --point-in-time <RFC3339 UTC>`; validate; add a `DATABASE_URL` pointing at the clone to the operator secret `ai-recruiter-production` (it overrides the Terraform value); `kubectl rollout restart` the deployments | < 1 h |
| Region loss | `terraform apply` the production environment with `region=europe-west3`, restore the latest multi-region backup into the new instance (`gcloud sql backups restore`), redeploy, update DNS. For a strict document RPO, use a dual-region bucket | < 8 h |
| Credential compromise | Rotate in Secret Manager (`terraform apply -replace=module.platform.random_password.jwt` for JWT_SECRET, which invalidates sessions); revoke refresh-token families; rotate integration secrets; review the audit log | < 1 h |

## Routine operations

- Seed a demo tenant: `kubectl exec deploy/ai-recruiter-api -- python -m scripts.seed --slug demo --password '<pw>'`
- Provision a tenant: `POST /api/v1/organizations` as super admin.
- Export OpenAPI: `python -m scripts.export_openapi docs/api/openapi.json`
- Regenerate ERD: `python -m scripts.export_erd docs/architecture/erd.md`
- Load test: `locust -f backend/tests/load/locustfile.py` (see the file header for targets)
