# Implementation Roadmap & Status

| Phase | Scope | Status |
|---|---|---|
| 1 | Architecture, PRD, SDD, ERD | ✅ `docs/product`, `docs/architecture` |
| 2 | Authentication, organizations, RBAC | ✅ JWT + refresh rotation, lockout, OIDC, magic links; 8 roles, 72 permissions, custom roles |
| 3 | Requisitions, jobs, ATS | ✅ AI-validated requisitions, approvals, JD agent, publishing, pipeline |
| 4 | Candidate management, CV processing | ✅ Secure intake, scanning, parsing with evidence, dedupe/merge, CRM |
| 5 | AI screening & matching | ✅ Rules + evidence + guardrails, explainable matching, review/override |
| 6 | Assessments, interviews, scheduling | ✅ Question bank, scoring, templates, slots, calendar adapters, transcripts, scorecards |
| 7 | Evaluation & offers | ✅ Consolidation, comparison, selection approval, verification, band-aware offers, approval chain |
| 8 | Onboarding integrations | ✅ Signed HRIS webhook, checklist, IT provisioning triggers |
| 9 | Analytics, observability, governance | ✅ KPIs + filters, fairness monitor, AI telemetry, audit, metrics, alerts |
| 10 | Security hardening, testing, deployment | ✅ Tests (unit/integration/API/security/RBAC/AI-eval/e2e/load), IaC, Helm, CI/CD |

## Verified in this repository

- Backend: 98 tests (unit, integration against PostgreSQL, security, RBAC, AI evaluation), 85% coverage; ruff and
  mypy clean; migrations round-trip with zero drift.
- Frontend: typecheck, lint and production build clean; Playwright e2e (5 scenarios) passing against the live stack.

## Not yet verified (needs the target cloud account)

- `terraform validate/plan/apply`, `helm lint/template`, container image builds and the CD pipeline run in GitHub
  Actions (no Terraform, Helm or Docker daemon was available in the authoring environment). Expect first-run fixes
  when these steps execute.
- Live calls to hosted LLM providers, Google/Microsoft calendars, Twilio and HRIS endpoints. Adapters follow each
  vendor's documented APIs and are covered by contract-style unit tests with fakes. Validate them against sandbox
  accounts before go-live.
- Production deployment itself (requires AWS credentials, DNS and TLS certificates).

## Next increments

1. pgvector/HNSW for semantic search at > 200k candidates per tenant; hosted embeddings by default.
2. Speech-to-text adapter (e.g. Whisper/Deepgram) feeding the Interview Assistant.
3. Offer e-signature integration (DocuSign/Adobe Sign) and a document template editor.
4. Per-tenant database encryption keys (envelope encryption with KMS data keys).
5. Row-level security in PostgreSQL as defence-in-depth for tenant isolation.
6. Job-board push APIs (LinkedIn, Indeed) where licensing permits; the XML feed is the current integration.
7. i18n of the candidate-facing UI and templates.
