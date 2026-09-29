# Operations Runbook: Monitoring, Alerting, Backup & DR

## Observability design

| Signal | Source | Where |
|---|---|---|
| Metrics | `/metrics` (Prometheus): `http_requests_total{method,route,status}`, `http_request_duration_seconds` histogram; Celery via flower/exporter; RDS/ElastiCache CloudWatch | Prometheus/Grafana, CloudWatch |
| Logs | Structured JSON to stdout with `request_id`, `org_id`, `user_id`; PII and secrets redacted at the formatter | Log shipper → CloudWatch / OpenSearch |
| Traces | Correlated by `X-Request-ID` (propagated from the web BFF); OpenTelemetry instrumentation can be enabled with `opentelemetry-instrument` without code changes | OTLP collector |
| AI telemetry | `ai_agent_executions` (latency, tokens, provider, model, prompt version, flags) | AI agents page, SQL |
| Business SLOs | Funnel, SLA breaches, fairness alerts | Analytics page |
| Health | `/healthz` (liveness), `/readyz` (DB + Redis) | Kubernetes probes, ALB |

### SLOs

- Availability 99.9%: error budget 43 min/month (5xx ratio).
- Latency: p95 < 300 ms reads, < 800 ms writes.

## Alerts (PrometheusRule + CloudWatch)

| Alert | Severity | First response |
|---|---|---|
| <a id="api-errors"></a>APIHighErrorRate (>2% 5xx, 10 min) | critical | Check the latest deploy (`helm history`); roll back if correlated. Inspect logs by `request_id`; check RDS/Redis health |
| <a id="latency"></a>APIHighLatency (p95 > 1 s) | warning | RDS Performance Insights top SQL; HPA saturation; LLM provider latency (AI agents page) |
| <a id="api-down"></a>APIDown | critical | `kubectl get pods -n ai-recruiter`; readiness failures usually mean DB or Redis; check the External Secrets sync |
| <a id="auth"></a>AuthFailureSpike | warning | Possible credential stuffing: confirm WAF rate rule is blocking; lockouts are automatic; consider tightening the WAF |
| <a id="abuse"></a>RateLimitingSpike | warning | Identify the IP or tenant; WAF block if malicious; contact the tenant if it's an integration misconfiguration |
| db-cpu / db-free-storage / redis-memory (CloudWatch → SNS) | warning | Scale the instance class or storage (autoscaling storage up to 5×); review slow queries |

## Backup strategy

| Data | Mechanism | Retention | RPO |
|---|---|---|---|
| PostgreSQL | RDS automated backups + PITR | 30 days (prod) | ≤ 5 min |
| PostgreSQL (DR) | Automated backup replication to eu-central-1 (KMS) | 14 days | ≤ 5 min (lag permitting) |
| PostgreSQL (release) | Manual snapshot before each production deploy | Until pruned (90 days) | n/a |
| Documents (S3) | Versioning; noncurrent versions expire after `document_retention_days` | 30 days | 0 |
| Redis | Daily snapshots (7 days). Redis holds only rebuildable state: queues, rate limits, results | 7 days | n/a |
| Configuration | Git (Helm, Terraform) + Secrets Manager versioning | ∞ / 30 versions | 0 |

**Restore drills run quarterly**: restore the latest PITR into staging, run migrations and the smoke suite, and record
the achieved RTO.

## Disaster recovery

| Scenario | Procedure | RTO |
|---|---|---|
| AZ failure | Automatic: Multi-AZ RDS failover, Redis failover, pods rescheduled across zones | Minutes |
| Accidental data change | `aws rds restore-db-instance-to-point-in-time --target-db-instance-identifier ai-recruiter-production-restore --restore-time <UTC>`; validate; update `DATABASE_URL` in Secrets Manager; restart deployments | < 1 h |
| Region loss | `terraform apply` the production environment in the DR region (`region=eu-central-1`), restore the replicated automated backup, replicate S3 (enable CRR for strict RPO), update DNS | < 8 h |
| Credential compromise | Rotate in Secrets Manager (JWT_SECRET rotation invalidates sessions); revoke refresh-token families; rotate integration secrets; review the audit log | < 1 h |

## Routine operations

- Seed a demo tenant: `kubectl exec deploy/ai-recruiter-api -- python -m scripts.seed --slug demo --password '<pw>'`
- Provision a tenant: `POST /api/v1/organizations` as super admin.
- Export OpenAPI: `python -m scripts.export_openapi docs/api/openapi.json`
- Regenerate ERD: `python -m scripts.export_erd docs/architecture/erd.md`
- Load test: `locust -f backend/tests/load/locustfile.py` (see the file header for targets)
