# AI Governance Model

## Policy statement

AI in AI Recruiter is **decision support**. It never makes a final employment decision. People decide to advance,
reject, select, set pay and hire, and every such decision is attributable and auditable.

## Controls

| Requirement | Implementation |
|---|---|
| Human approval gates | `domain/pipeline.py` `HUMAN_GATES` + `move_stage` choke point; the orchestrator interrupts on `human` nodes; approval workflows for requisitions, selection and offers with segregation of duties |
| Explainable recommendations | Rule-by-rule results with pass/fail detail; per-requirement match explanation; competency matrix; stated rationale |
| Evidence-backed summaries | Facts carry verbatim evidence quotes; AI interpretations are labelled and visually separated |
| Configurable screening rules | Per-job requirements (kind, weight, mandatory, min years), knock-out questions and thresholds |
| Recruiter override | Allowed at every step; disagreeing with the AI requires a documented reason (≥10 chars), stored as `overridden` |
| Audit trails | Append-only audit log; `ai_agent_executions`; `ai_recommendations` with review outcome |
| Bias & fairness monitoring | Voluntary EEO data kept separate from screening; four-fifths adverse-impact monitor per stage and dimension (groups <5 suppressed); alerts surface as critical insights; CI counterfactual and adverse-impact tests |
| Privacy controls | PII minimisation in logs and AI inputs; field encryption; role-gated PII |
| Data retention | Org-level `data_retention_days`; nightly purge anonymises expired candidates without active applications; S3 noncurrent versions expire |
| Consent management | Per-purpose consent records (processing, AI screening, talent pool, recording, background check) with expiry; AI screening is skipped without consent and routed to manual review |
| Right to erasure / access | Irreversible anonymisation (documents deleted, PII overwritten, embeddings dropped); JSON export for data-subject access requests; candidate self-service in the portal |
| Encryption | See security model |
| Prompt-injection protection | See `docs/architecture/agents.md#guardrails` |
| AI/model logging & evaluation | Provider, model and prompt version per execution; tokens and latency; guardrail flags; human–AI agreement dashboard; offline eval suite in CI |
| Per-tenant switches | `ai_screening_enabled`, `auto_screen_on_apply`, `ai_interview_summaries_enabled`, `require_consent_for_ai`, `bias_monitoring_enabled`, `adverse_impact_threshold` |

## Roles and responsibilities

- **Org Admin:** owns the governance policy and integrations.
- **HR Manager:** reviews fairness alerts weekly, handles erasure requests within 30 days, runs retention.
- **Recruiters and hiring managers:** make decisions and document overrides.
- **Platform team:** model and prompt changes go through review. Bump the prompt version and run the eval suite; a PR
  that fails fairness thresholds cannot merge.

## Change management for models and prompts

1. Change the prompt or model and bump the version in `app/ai/prompts.py`.
2. `pytest tests/ai_eval` with the target provider must meet all thresholds.
3. Deploy to staging, monitor agreement rate and guardrail flags for one week, then promote.
4. Rollback: revert `LLM_MODEL`/prompt or set `LLM_PROVIDER=local` (instant, no redeploy of code required).

## Regulatory alignment (non-exhaustive)

- **EU AI Act** (employment is high-risk): human oversight, logging, transparency to candidates (FAQ and application
  form disclose AI use), data governance, accuracy and robustness testing.
- **GDPR / POPIA**: lawful basis via consent, purpose limitation, minimisation, retention, erasure, access.
- **NYC Local Law 144 / EEOC guidance**: bias-audit metrics (selection rates, impact ratios) are available from
  `/api/v1/analytics/fairness`, exportable for independent audits.
