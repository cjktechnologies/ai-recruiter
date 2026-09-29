# Product Requirements Document — AI Recruiter

| | |
|---|---|
| Product | AI Recruiter: AI-assisted Recruitment Operations Platform |
| Type | Commercial multi-tenant SaaS (SME → enterprise) |
| Status | v1.0 implemented (see `docs/roadmap.md` for scope status) |

## 1. Problem

Recruitment teams juggle requisition approvals, job adverts, high application volumes, scheduling across calendars,
inconsistent interview feedback, slow offer approvals and a manual HR handoff. Teams adopting AI face a second problem:
opaque screening that can't be explained, audited or defended, and that risks discriminating against candidates.

## 2. Goals

1. Automate the end-to-end hiring workflow, from approved requisition to onboarding handoff, in one system: ATS, CRM,
   assessments, interviews, offers and analytics.
2. Use AI where it saves time: parsing, matching, evidence summaries, scheduling, JD drafting, offer drafting and insights.
3. Keep every consequential decision with a human: advancing, rejecting, selecting, approving pay and hiring.
4. Make every AI output explainable and auditable, and monitor it for bias.
5. Be secure and privacy-preserving by default (GDPR/POPIA-style consent, retention and erasure).

### Non-goals (v1)
- Autonomous hiring or rejection by AI.
- Scraping third-party sites for candidates. Sourcing covers consented talent pools and approved job-board channels only.
- Payroll processing. The platform hands off to HRIS/payroll systems; it does not replace them.

## 3. Personas and roles

| Role | Primary jobs |
|---|---|
| Super Admin | Provision tenants and operate the platform |
| Organization Admin | Users, roles, integrations, AI governance policy |
| HR Manager | Approve requisitions and selections, run fairness monitoring, own retention and erasure |
| Recruiter | Run the pipeline: jobs, screening review, assessments, scheduling, verification, offers |
| Hiring Manager | Raise and approve requisitions, interview, make evaluation decisions |
| Interviewer | Conduct interviews and submit independent scorecards |
| Finance/Approver | Approve budgets and out-of-band compensation |
| Candidate | Apply, take assessments, respond to offers, track status, control own data |

## 4. Core flow

Hiring Requisition → Approval → JD → Job Posting → Applications/Sourcing → AI Screening → **Human Review** →
Assessment → Interview → Evaluation → **Selection Approval** → Verification → Offer → **Offer Approval** → Acceptance →
HRIS/Onboarding. Bold steps are hard human gates enforced by the pipeline state machine.

## 5. Functional requirements (all implemented in v1)

| Module | Requirements |
|---|---|
| Recruitment management | Requisitions with AI validation; multi-step approvals (role-based, segregation of duties); JD and advert generation; publishing to the careers site and XML job-board feed; kanban pipeline; stages and statuses; talent pools |
| Candidate management | Profiles; secure CV upload (type sniffing, macro and active-content rejection, malware scan); parsing with evidence; skills and experience extraction; search (text and skill); explainable matching; duplicate detection and merge; notes; communication history |
| Screening | Rule-based eligibility (mandatory requirements and knock-out questions); AI-assisted, evidence-based summaries; configurable thresholds; recruiter review; an override requires a documented reason |
| Assessment | Technical and competency assessments; question bank; generation from job skills; auto-scoring of objective items; human scoring of free text; results and candidate feedback |
| Interview management | Structured templates; scorecards (independent, competency-based); slot suggestion across panel availability; Google Calendar and Microsoft Graph integration; reminders; notes; AI transcript summaries with competency evidence |
| Selection and offers | Comparison workspace; evaluation consolidation; selection approval; references (tokenised referee form); background checks (consent, provider webhook); compensation bands; offer drafting within bands; approval chain; secure offer link; accept/decline tracking; expiry |
| Onboarding | Idempotent HRIS handoff (signed webhook); preboarding checklist; IT provisioning triggers; HR tasks |
| Analytics | Time-to-fill, time-to-hire, cost-per-hire, volume, screening/interview conversion, offer acceptance, source of hire and effectiveness, funnel, SLA, recruiter/HM/interviewer workload, assessment performance, quality-of-hire indicators, adverse-impact monitoring; filters by department, position, recruiter, hiring manager, source, date range and location |
| Communications | Templated e-mail/SMS/WhatsApp; FAQ chatbot grounded in the org knowledge base; candidate portal (status, withdraw, export, erasure request) |
| Governance | Audit log (DB-enforced append-only); AI execution logs; recommendation review and agreement metrics; consent records; retention policy; right to erasure; data-subject export |

## 6. Non-functional requirements

| Area | Target |
|---|---|
| Availability | 99.9% monthly (multi-AZ data tier, ≥2 replicas per tier, PDBs) |
| Latency | p95 < 300 ms for reads, < 800 ms for applications with AI screening (deterministic path) |
| Scale | 10k tenants, 1M candidates per large tenant; horizontal API/worker scaling |
| Security | OWASP ASVS L2 controls; see `docs/security/security-model.md` |
| Privacy | Consent per purpose; retention default 730 days (configurable 30–3650); erasure within 30 days |
| Recovery | RPO ≤ 5 min (PITR), RTO ≤ 1 h in-region; cross-region backups for DR (RTO ≤ 8 h) |
| Accessibility | WCAG 2.2 AA for staff and candidate UIs |

## 7. Success metrics

- Time-to-hire reduced 30% within two quarters of adoption.
- Recruiter hours per hire reduced 40%.
- ≥ 85% human–AI agreement on screening, with every override documented.
- No adverse-impact alert left unreviewed for more than 7 days.
- Candidate NPS ≥ 40; offer acceptance ≥ 80%.

## 8. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Biased AI recommendations | Protected-attribute exclusion; output scrubbing; counterfactual evaluation in CI; four-fifths monitoring; humans decide |
| Prompt injection via CVs | Sanitisation, detection, delimiting; suspicious documents never get positive recommendations |
| Vendor/model outage | Provider abstraction plus a deterministic fallback path; the platform stays fully functional without an LLM |
| Regulatory change (EU AI Act, NYC LL144) | Audit trail, explainability, bias metrics exportable for audits; AI features can be disabled per tenant |
