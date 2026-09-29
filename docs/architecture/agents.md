# Agent Architecture

## Principles

1. **Deterministic core, generative enrichment.** Every agent computes facts deterministically: rule checks, parsed
   evidence, scores, schedules, band maths. It then optionally asks an LLM for narrative or interpretation. With
   `LLM_PROVIDER=local` (or during a provider outage) the platform is fully functional.
2. **Facts ≠ interpretations.** Outputs carry `facts[]` (each with an evidence quote and a source) separately from
   `interpretations[]` (flagged `ai_generated`). The UI renders them in visually distinct blocks.
3. **Advisory only.** Agents never cross human gates (enforced in `services.applications.move_stage`).
4. **Everything is logged.** `ai_agent_executions` records the provider, model, prompt version, redacted input
   summary, output, tokens, latency and guardrail flags. `ai_recommendations` records every consequential suggestion
   and the human's review of it (accepted or overridden), which feeds the agreement metrics.

## Agent catalogue

| Agent | Module | Deterministic core | LLM enrichment | Output consumed by |
|---|---|---|---|---|
| Recruitment Requisition | `requisition.py` | Completeness, budget vs band, start-date realism, exclusionary language, approval routing | Risk review | Requisition submit / approval route |
| Job Description | `job_description.py` | Inclusive template, requirement extraction | Full JD + advert (checked for exclusionary terms) | Job drafts |
| Talent Sourcing | `sourcing.py` | Ranks *consented* talent-pool candidates by match | — | Sourcing tab |
| Candidate Screening | `screening.py` | Requirement rules, knock-outs, eligibility, evidence facts, thresholds | Strengths / gaps / probes / recommendation (capped if ineligible) | Screening review gate |
| Candidate Matching | `matching.py` | Weighted coverage + semantic similarity, per-requirement explanation | — | Screening, sourcing, pipeline cards |
| Candidate Communication | `communication.py` | Templates, FAQ retrieval, status answers, escalation | Grounded answer from knowledge base | Careers chat, portal chat, notifications |
| Assessment | `assessment.py` | Question-bank assembly by skill; objective scoring; rubric keyword suggestions | — | Assessments |
| Interview Scheduling | `scheduling.py` | Multi-timezone availability, working hours, buffers, per-day caps, slot scoring | — | Slot suggestions |
| Interview Assistant | `interview_assistant.py` | Candidate-quote extraction per competency, evidence strength | Neutral summary + mapping | Interview record, evaluation |
| Candidate Evaluation | `evaluation.py` | Weighted evidence score, competency matrix, disagreement and missing-feedback risks | Balanced rationale | Evaluation decision gate |
| Offer | `offer.py` | Band positioning, budget cap, bonus policy, approval chain (finance if out of band) | Letter prose (rejected if its figures don't match) | Offer drafts |
| Recruitment Analytics | `analytics.py` | SLA breaches, acceptance, source effectiveness, fairness alerts | Additional insights | Dashboard, analytics |
| Onboarding Handoff | `onboarding.py` | HRIS payload, preboarding tasks, IT provisioning | — | Onboarding |

## Provider abstraction

`app/ai/providers/base.py` defines `LLMProvider.complete_json(system, user, schema)`, which returns validated
Pydantic data plus token usage. Adapters:

- **Anthropic** (`anthropic` SDK): default model `claude-opus-5-5`, structured outputs via
  `output_config.format` (JSON schema), configurable `effort`, and server-side refusal fallbacks
  (`fallbacks="default"`). Refusals and truncation raise typed errors.
- **OpenAI** (`openai` SDK): JSON-schema `response_format` with `strict: true`.
- **Gemini** (`google-genai` SDK): `response_schema`.
- **Local:** no generation; agents use their deterministic path.

Any provider error is caught in `BaseAgent.ask_llm`. The run continues deterministically and records
`llm_unavailable:<Error>`.

## Guardrails (`app/ai/guardrails.py`)

| Threat | Control |
|---|---|
| Prompt injection in CVs, transcripts or chat | NFKC normalisation, zero-width/control stripping, length caps; pattern detection (override, role hijack, prompt probes, score manipulation, hire directives, chat-template markup); `<untrusted_data>` delimiting with delimiter neutralisation; system prompts forbid following embedded instructions |
| Manipulated documents | Flagged documents skip the LLM and **cannot receive a positive recommendation**; the audit log records `document.injection_suspected` |
| Bias | Prompts forbid protected characteristics and proxies; AI text is scanned for protected-attribute references and scrubbed; EEO data is stored separately and never shown to agents |
| Hallucinated facts | Facts come only from deterministic extraction with evidence; offer letters are rejected unless their figures match approved values |
| Over-reach | Screening recommendations are capped when mandatory criteria fail; agents cannot move gated stages |

## Evaluation

`backend/tests/ai_eval` runs on a synthetic, seeded dataset (`tests/fixtures/synthetic.py`): 4 roles × 24 candidates,
with demographic signals independent of qualification. Every CI run checks:

- eligibility precision/recall ≥ 0.95; recommendation accuracy ≥ 0.85; NDCG@10 ≥ 0.9 per role;
- every candidate-material fact quotes the source;
- **counterfactual fairness**: swapping names, pronouns and demographic-signalling text changes neither eligibility
  nor recommendation (score delta ≤ 2);
- **adverse impact**: selection-rate ratio ≥ 0.8 across name sets;
- **injection robustness**: attacked CVs never receive positive recommendations.

To evaluate a hosted model, set `LLM_PROVIDER` and its API key and run `pytest tests/ai_eval -s`. The same thresholds
apply. In production, `/api/v1/ai/evaluation` reports human–AI agreement per agent from real reviews.

## Prompts

System prompts are versioned in `app/ai/prompts.py`. The version is stored on every execution, so outcomes can be
traced back to the exact wording. Every recruitment-facing prompt embeds a shared fairness policy and an
untrusted-data policy.
