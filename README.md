# AI Recruiter

A multi-tenant SaaS recruitment operations platform: ATS, CRM, workflow automation and AI decision support. It covers
the full hiring lifecycle, from an approved requisition to onboarding handoff. **AI recommends; people decide.**

```
Requisition → Approval → JD → Job posting → Applications/Sourcing → AI screening → HUMAN REVIEW → Assessment →
Interview → Evaluation → SELECTION APPROVAL → Verification → Offer → OFFER APPROVAL → Acceptance → HRIS/Onboarding
```

## What's inside

| Path | Contents |
|---|---|
| `backend/` | FastAPI + SQLAlchemy + Alembic + Celery. 13 AI agents, a durable orchestrator with human-in-the-loop interrupts, and 158 REST operations |
| `frontend/` | Next.js 16 + TypeScript + Tailwind: staff workspaces, careers site and candidate portal (BFF with httpOnly sessions) |
| `backend/vercel.json`, `frontend/vercel.json` | Vercel projects (default production target): FastAPI on the Python runtime + Next.js, Neon, Upstash, private Blob, Cron |
| `deploy/helm/` | Kubernetes Helm chart (API, workers, beat, web, migration hook, HPA/PDB, NetworkPolicies, alerts) |
| `infra/terraform/` | Google Cloud: VPC, GKE, Cloud SQL PostgreSQL, Memorystore, Cloud Storage, Cloud KMS, Artifact Registry, Cloud Armor, Secret Manager, GitHub Workload Identity Federation |
| `.github/workflows/` | CI (tests, e2e, IaC validation), security scanning, CD (staging → approved production, rollback) |
| `docs/` | PRD, SDD, ERD, agent architecture, security model, AI governance, UI spec, API docs, deployment, runbook, guides |

## Quick start (local)

```bash
cp .env.example .env
docker compose up --build        # web :3000, API :8000/docs, mail :8025
docker compose exec api python -m scripts.seed --slug demo --password 'Demo!Passw0rd123'
```

Sign in at http://localhost:3000 as `recruiter@demo.example.com` (other roles: `admin@`, `hr.manager@`,
`hiring.manager@`, `interviewer@`, `finance.approver@`). The careers site is at http://localhost:3000/careers/demo.

The default `LLM_PROVIDER=local` runs every agent on its deterministic, evidence-based path with no external calls. To
enable generative enrichment, set `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY` (default model `claude-opus-5-5`),
or use `openai` / `gemini`.

### Without Docker

```bash
python3.11 -m venv .venv && . .venv/bin/activate && pip install -r backend/requirements-dev.txt
cd backend && alembic upgrade head && TASK_ALWAYS_EAGER=true uvicorn app.main:app --reload
cd frontend && npm ci && BACKEND_URL=http://localhost:8000 npm run dev
```

## Testing

```bash
cd backend && pytest --cov=app          # unit, integration (PostgreSQL), security, RBAC, AI evaluation
ruff check . && mypy app
cd frontend && npm run lint && npm run typecheck && npm run build && npx playwright test   # e2e needs the stack running
locust -f backend/tests/load/locustfile.py                                                # performance
```

## Documentation

Start with [`docs/product/PRD.md`](docs/product/PRD.md) and [`docs/architecture/SDD.md`](docs/architecture/SDD.md).
Then see [agents](docs/architecture/agents.md), [ERD](docs/architecture/erd.md),
[security](docs/security/security-model.md), [AI governance](docs/governance/ai-governance.md),
[API](docs/api/README.md), [UI spec](docs/ux/ui-spec.md), [Vercel deployment](docs/operations/vercel.md),
[Google Cloud deployment](docs/operations/deployment.md),
[runbook](docs/operations/runbook.md), [admin guide](docs/guides/admin-guide.md),
[user guide](docs/guides/user-guide.md) and [roadmap & status](docs/roadmap.md).
