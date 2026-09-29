"""Interview Assistant Agent: structured summaries and competency evidence from transcripts."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.ai.agents.base import AgentContext, BaseAgent, RunState
from app.ai.guardrails import sanitize_untrusted, scrub_protected, validate_ai_rationale, wrap_untrusted
from app.domain.enums import AgentName


class Competency(BaseModel):
    name: str
    description: str | None = None
    keywords: list[str] = Field(default_factory=list)


class InterviewInput(BaseModel):
    transcript: str
    competencies: list[Competency]
    interviewer_notes: str | None = None


class CompetencyEvidence(BaseModel):
    competency: str
    quotes: list[str]
    evidence_strength: str  # none|limited|moderate|strong
    ai_generated: bool = False


class InterviewSummary(BaseModel):
    summary: str
    competency_evidence: list[CompetencyEvidence]
    follow_up_questions: list[str]
    facts: list[str]
    interpretations: list[str]
    ai_generated: bool


class LLMInterview(BaseModel):
    summary: str
    competency_evidence: list[CompetencyEvidence]
    follow_up_questions: list[str]
    security_notes: list[str]


_SENT = re.compile(r"(?<=[.!?])\s+|\n+")


def _candidate_lines(transcript: str) -> list[str]:
    """Prefer lines attributed to the candidate ("Candidate:" / "C:"); fall back to all sentences."""
    lines = [ln.strip() for ln in transcript.splitlines() if ln.strip()]
    cand = [re.sub(r"^(candidate|c)\s*:\s*", "", ln, flags=re.I) for ln in lines if re.match(r"^(candidate|c)\s*:", ln, re.I)]
    return cand or [s.strip() for s in _SENT.split(transcript) if s.strip()]


def extract_evidence(transcript: str, competencies: list[Competency]) -> list[CompetencyEvidence]:
    sentences = [s for ln in _candidate_lines(transcript) for s in _SENT.split(ln) if len(s.split()) >= 4]
    out = []
    for comp in competencies:
        keys = [k.lower() for k in (comp.keywords or re.findall(r"[a-zA-Z]{4,}", comp.name))]
        quotes = [s for s in sentences if any(k in s.lower() for k in keys)][:4]
        strength = "none" if not quotes else "limited" if len(quotes) == 1 else "moderate" if len(quotes) < 4 else "strong"
        out.append(CompetencyEvidence(competency=comp.name, quotes=[q[:300] for q in quotes], evidence_strength=strength))
    return out


class InterviewAssistantAgent(BaseAgent[InterviewInput, InterviewSummary]):
    name = AgentName.INTERVIEW_ASSISTANT
    prompt_key = "interview_assistant"

    def summarize_input(self, payload: InterviewInput) -> dict:
        return {"transcript_chars": len(payload.transcript), "competencies": [c.name for c in payload.competencies]}

    def execute(self, ctx: AgentContext, p: InterviewInput, state: RunState) -> InterviewSummary:
        clean = sanitize_untrusted(p.transcript)
        state.flags.extend(clean.flags)
        evidence = extract_evidence(clean.text, p.competencies)
        gaps = [e.competency for e in evidence if e.evidence_strength in ("none", "limited")]
        facts = [f"{e.competency}: {len(e.quotes)} candidate statement(s) referenced" for e in evidence]
        summary = (
            f"Transcript covers {len(p.competencies)} competencies; evidence found for "
            f"{sum(1 for e in evidence if e.quotes)}. Limited or no evidence for: {', '.join(gaps) or 'none'}."
        )
        result = InterviewSummary(
            summary=summary, competency_evidence=evidence,
            follow_up_questions=[f"Ask for a concrete example demonstrating {g}." for g in gaps],
            facts=facts, interpretations=[], ai_generated=False,
        )
        if clean.is_suspicious:
            state.flags.append("llm_skipped:suspected_prompt_injection")
            return result
        comps = "\n".join(f"- {c.name}: {c.description or ''}" for c in p.competencies)
        llm = self.ask_llm(state, schema=LLMInterview, user=(
            f"Competencies:\n{comps}\n\nInterviewer notes: {p.interviewer_notes or 'none'}\n\n"
            f"{wrap_untrusted('interview_transcript', clean.text)}"
        ))
        if llm:
            flags = validate_ai_rationale(llm.summary)
            if flags:
                state.flags.extend(flags)
                llm.summary = scrub_protected(llm.summary)
            for ev in llm.competency_evidence:
                ev.ai_generated = True
            result = InterviewSummary(
                summary=llm.summary, competency_evidence=llm.competency_evidence,
                follow_up_questions=llm.follow_up_questions, facts=facts,
                interpretations=[llm.summary], ai_generated=True,
            )
        return result
