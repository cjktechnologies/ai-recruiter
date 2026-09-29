# UI/UX Specification

## Design principles

1. **Decision workspaces, not data dumps.** Each screen answers "what needs my decision, and what's the evidence?"
2. **Facts vs AI, always distinguishable.** Extracted facts show quoted evidence. AI interpretation sits in a
   violet-tinted panel with a `✦ AI-generated` badge. Rule-based output says "Rule-based".
3. **Humans hold the pen.** Decision controls (Advance / Reject / Approve) are explicit buttons. Disagreeing with the AI
   prompts for a reason. The orchestrator banner shows what the workflow is waiting on.
4. **Role-aware.** Navigation and actions render only when the user has the permission; the API still enforces it.
5. **Accessible:** WCAG 2.2 AA. Semantic landmarks, labelled controls, visible focus rings, colour never the sole
   signal (badges carry text), charts with a table view and tooltips, light/dark tokens.

## Layout

App shell with a left navigation (collapses to a select on mobile) and a top bar with the AI-advisory reminder,
notifications, the user and sign-out. Content max width 1280 px, 16 px gutters.

## Screens

| Screen | Route | Purpose / key elements |
|---|---|---|
| Recruitment dashboard | `/dashboard` | KPI tiles; pipeline funnel; AI insights; applications/week; pending approvals; my interviews |
| Requisitions | `/requisitions`, `/new`, `/[id]` | Filterable list; form; AI validation panel (issues by severity, completeness, route); approval timeline with approve/reject; "Create job (AI-drafted JD)" |
| Jobs & pipeline | `/jobs`, `/[id]` | Kanban by stage with match scores; description with JD-agent draft → accept; requirements editor (weights, mandatory); knock-outs; consented sourcing |
| Candidates | `/candidates`, `/[id]` | Search by text and skill; profile tabs: skills **with evidence quotes**, experience, education; documents with scan/parse status and security flags; notes; communications; consents; duplicate banner + merge; DSAR export; erasure |
| AI screening workspace | `/screening` | Queue ranked by match; eligibility; AI recommendation; summary; multi-select → compare |
| Candidate workspace | `/applications/[id]` | Stage stepper; orchestrator status; screening (facts, rule checks, interpretation, decision); assessments (invite, review free text); interviews (slot suggestions → schedule); evaluation (matrix, risks, decision with rationale); selection approval; verification; offer; onboarding; timeline (agent vs user actions) |
| Assessment dashboard | `/assessments` | Assessments; question bank; add question; generate for job |
| Interview calendar | `/interviews` | Week view, navigation, cards per interview |
| Interview & scorecard | `/interviews/[id]` | Structured guide; AI assistant (transcript → summary and competency quotes, consent checkbox); independent scorecard; submitted cards |
| Candidate comparison | `/comparison?ids=` | Side-by-side evidence rows, including competencies and risks |
| Offer management | `/offers`, `/[id]` | List; terms (band indicator); approval chain; letter; submit/approve/send/withdraw |
| Onboarding | `/onboarding` | Checklist with status changes |
| Recruitment analytics | `/analytics` | Filters in one row (department, position, source, location, date range); KPI tiles; funnel; volume; SLA; sources; workloads; assessment and quality-of-hire metrics; fairness table (governance roles) |
| AI agent monitoring | `/agents` | Runs/failures; workflows waiting per gate; agreement per agent; executions with model/prompt/latency/tokens/flags |
| Audit log | `/audit` | Filterable, paginated, actor-type badges |
| Administration | `/admin` | Users, roles, departments, compensation bands, integrations (write-only secrets), AI governance policy + retention |
| Careers site | `/careers/[org]`, `/[slug]` | Job list, FAQ assistant, application form with consent choices and optional EEO survey |
| Candidate links | `/assessment/[token]`, `/offer/[token]`, `/reference/[token]` | Single-purpose, tokenised, no account needed |
| Candidate portal | `/portal` | Magic-link sign-in; status; withdraw; chat; export; erasure request |

## Visual system

Tokens in `frontend/src/app/globals.css`: neutral surfaces, one accent (blue), status colours (good, warn, serious,
critical) reserved for state, and violet reserved for AI. Charts are single-series magnitude bars in one hue with
direct labels, a hover tooltip and a table toggle. Dark mode uses selected (not inverted) values.
