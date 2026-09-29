# API Documentation

- **Spec:** [`openapi.json`](openapi.json) (OpenAPI 3.1, 123 paths / 158 operations). Regenerate with
  `cd backend && python -m scripts.export_openapi ../docs/api/openapi.json`; CI fails if it is stale.
- **Interactive docs:** `GET /docs` (Swagger UI) and `GET /redoc` on any running API.

## Conventions

| Concern | Convention |
|---|---|
| Base path / versioning | `/api/v1`. Breaking changes ship as `/api/v2` alongside v1 |
| Auth | `Authorization: Bearer <access_token>`, from `POST /auth/login`, `POST /auth/refresh`, OIDC (`/auth/oidc/login`), or candidate magic links (`/auth/candidate/verify`). Super admins pick a tenant with `X-Organization-Id` |
| Errors | `application/problem+json`: `{type,title,status,detail,code,request_id[,errors]}`. Codes: `unauthenticated`, `forbidden`, `not_found`, `conflict`, `invalid_transition`, `approval_required`, `validation_failed`, `unsafe_content`, `rate_limited` |
| Pagination | `?page=1&page_size=25` (max 200) → `{items,total,page,page_size}` |
| Sorting | `?sort=-created_at,title` (whitelisted per resource) |
| Filtering | Resource-specific query parameters (e.g. `/applications?job_id=&stage=screened&stage=interview&min_score=60`) |
| Idempotency | `Idempotency-Key: <8-200 chars>` on critical POSTs; retries return the original response; body mismatch → 422 |
| Rate limiting | 429 + `Retry-After` |
| Tracing | `X-Request-ID` echoed or generated on every response |

## Resource map

| Area | Key endpoints |
|---|---|
| Authentication | `POST /auth/login`, `/auth/refresh`, `/auth/logout`, `GET /auth/me`, OIDC login/callback, candidate verify |
| Organizations & users | `/organizations` (super admin), `/organization`, `/departments`, `/users`, `/roles`, `/permissions`, `/compensation-bands` |
| Requisitions | `/requisitions`, `/{id}/submit` (AI validation → approvals), `/{id}/decision`, `/{id}/jobs` (AI JD) |
| Jobs & sourcing | `/jobs`, `/{id}/requirements`, `/{id}/generate-description`, `/{id}/publish`, `/{id}/close`, `/{id}/pipeline`, `/{id}/sourcing`, `/talent-pools` |
| Candidates | `/candidates` (search), `/{id}`, `/{id}/documents` (upload/list/download), `/notes`, `/consents`, `/duplicates`, `/merge`, `/communications`, `/messages`, `/export`, `DELETE` (erasure) |
| Applications & screening | `/applications`, `/{id}/move`, `/{id}/reject`, `/{id}/screening`, `/screening/queue`, `/screening/{id}/review` |
| Assessments | `/question-bank`, `/assessments`, `/assessments/generate`, `/applications/{id}/assessments`, `/assessment-results/{id}/score` |
| Interviews & scheduling | `/interview-templates`, `/applications/{id}/interview-slots`, `/applications/{id}/interviews`, `/interviews` (calendar), `/{id}/cancel`, `/{id}/complete`, `/{id}/transcript`, `/{id}/scorecards` |
| Evaluation & selection | `/applications/{id}/evaluations`, `/evaluations/{id}/decision`, `/applications/{id}/selection`, `/comparison` |
| Verification | `/applications/{id}/references`, `/applications/{id}/background-checks`, `/background-checks/{id}`, `/webhooks/background-checks/{integration_id}` |
| Offers | `/applications/{id}/offers`, `/offers`, `/{id}` (PATCH), `/{id}/submit`, `/{id}/decision`, `/{id}/send`, `/{id}/record-response`, `/{id}/withdraw` |
| Onboarding | `/applications/{id}/onboarding` (handoff), `/onboarding/tasks` |
| Analytics | `/analytics/overview`, `/analytics/fairness`, `/analytics/insights` |
| AI agents & governance | `/agents`, `/agents/executions`, `/ai/recommendations`, `/ai/evaluation`, `/workflows`, `/workflows/graph`, `/applications/{id}/workflow`, `/governance/policy`, `/governance/retention/run`, `/audit-logs` |
| Notifications & integrations | `/notifications`, `/integrations` |
| Candidate portal | `/portal/applications`, `/portal/applications/{id}/withdraw`, `/portal/me/export`, `/portal/me/erasure-request`, `/portal/chat` |
| Public | `/public/{org}/jobs`, `/jobs.xml`, `/jobs/{slug}`, `/jobs/{slug}/apply`, `/chat`, `/portal/link`, `/assessments/{token}`, `/offers/{token}`, `/references/{token}` |
