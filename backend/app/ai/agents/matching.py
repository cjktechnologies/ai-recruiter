"""Candidate Matching Agent: explainable weighted requirement coverage + semantic similarity."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.ai.agents.base import AgentContext, BaseAgent, RunState
from app.ai.embeddings import cosine
from app.ai.taxonomy import normalize_skill
from app.domain.enums import AgentName

SEMANTIC_WEIGHT = 0.25  # share of the score from embedding similarity; the rest is explainable coverage


class RequirementIn(BaseModel):
    kind: str
    name: str
    min_years: float | None = None
    is_mandatory: bool = False
    weight: float = 1.0


class CandidateSkillIn(BaseModel):
    name: str
    years: float | None = None
    evidence: str | None = None


class MatchInput(BaseModel):
    requirements: list[RequirementIn]
    job_embedding: list[float] | None = None
    candidate_skills: list[CandidateSkillIn]
    candidate_years: float | None = None
    candidate_embedding: list[float] | None = None
    candidate_location: str | None = None
    candidate_languages: list[str] = Field(default_factory=list)
    candidate_education: list[str] = Field(default_factory=list)
    candidate_certifications: list[str] = Field(default_factory=list)

    def summarize(self) -> dict:
        return {"requirements": len(self.requirements), "skills": len(self.candidate_skills)}


class RequirementMatch(BaseModel):
    requirement: str
    kind: str
    mandatory: bool
    weight: float
    matched: bool
    partial: float = Field(ge=0, le=1)
    evidence: str | None = None
    detail: str


class MatchOutput(BaseModel):
    score: float = Field(ge=0, le=100)
    coverage_score: float
    semantic_similarity: float
    mandatory_met: bool
    matches: list[RequirementMatch]


_EDU_RANK = {
    "diploma": 1,
    "associate": 1,
    "hnd": 1,
    "national diploma": 1,
    "bachelor": 2,
    "bsc": 2,
    "ba": 2,
    "bs": 2,
    "beng": 2,
    "btech": 2,
    "master": 3,
    "msc": 3,
    "ms": 3,
    "mba": 3,
    "meng": 3,
    "phd": 4,
    "doctorate": 4,
}


def _edu_rank(text: str) -> int:
    t = text.lower().replace(".", "").replace("'s", "")
    return max((r for k, r in _EDU_RANK.items() if k in t), default=0)


def compute_match(inp: MatchInput) -> MatchOutput:
    skills = {normalize_skill(s.name).lower(): s for s in inp.candidate_skills}
    matches: list[RequirementMatch] = []
    for req in inp.requirements:
        kind = req.kind
        matched, partial, evidence, detail = False, 0.0, None, ""
        if kind == "skill":
            s = skills.get(normalize_skill(req.name).lower())
            if s:
                evidence = s.evidence
                if req.min_years and s.years is not None and s.years < req.min_years:
                    partial = max(0.3, s.years / req.min_years)
                    detail = f"Has {req.name} ({s.years}y) but below {req.min_years}y"
                else:
                    matched, partial, detail = True, 1.0, f"{req.name} found in candidate material"
            else:
                detail = f"No evidence of {req.name}"
        elif kind == "experience":
            yrs = inp.candidate_years
            need = req.min_years or 0
            if yrs is None:
                detail = "Years of experience could not be determined"
            elif yrs >= need:
                matched, partial, detail = True, 1.0, f"{yrs}y experience ≥ required {need}y"
            else:
                partial = max(0.0, yrs / need) if need else 0.0
                detail = f"{yrs}y experience < required {need}y"
        elif kind == "education":
            need_rank = _edu_rank(req.name) or 2
            best = max((_edu_rank(e) for e in inp.candidate_education), default=0)
            if best >= need_rank:
                matched, partial = True, 1.0
                evidence = next((e for e in inp.candidate_education if _edu_rank(e) == best), None)
                detail = "Education requirement met"
            else:
                partial = best / need_rank if need_rank else 0
                detail = "Required education level not evidenced"
        elif kind == "certification":
            hit = next((c for c in inp.candidate_certifications if req.name.lower() in c.lower()), None)
            matched, partial, evidence = bool(hit), 1.0 if hit else 0.0, hit
            detail = "Certification found" if hit else f"{req.name} not evidenced"
        elif kind == "language":
            hit = next((lang for lang in inp.candidate_languages if lang.lower() == req.name.lower()), None)
            matched, partial, evidence = bool(hit), 1.0 if hit else 0.0, hit
            detail = "Language listed" if hit else f"{req.name} not listed"
        elif kind == "location":
            loc = (inp.candidate_location or "").lower()
            loc_ok = bool(loc) and (req.name.lower() in loc or loc in req.name.lower())
            matched, partial, evidence = loc_ok, 1.0 if loc_ok else 0.0, inp.candidate_location
            detail = "Location matches" if loc_ok else "Location not confirmed — verify with candidate"
        else:  # work_authorization and other human-verified criteria
            detail = "Requires recruiter verification"
            partial = 0.5
        matches.append(
            RequirementMatch(
                requirement=req.name,
                kind=kind,
                mandatory=req.is_mandatory,
                weight=req.weight,
                matched=matched,
                partial=round(partial, 3),
                evidence=evidence,
                detail=detail,
            )
        )
    total_w = sum(m.weight for m in matches) or 1.0
    coverage = sum(m.weight * m.partial for m in matches) / total_w if matches else 0.5
    semantic = max(0.0, cosine(inp.job_embedding, inp.candidate_embedding))
    # Hash embeddings rarely exceed ~0.6 similarity; rescale into [0,1] for interpretability.
    semantic_scaled = min(1.0, semantic / 0.6) if semantic else 0.0
    weight = SEMANTIC_WEIGHT if inp.job_embedding and inp.candidate_embedding else 0.0
    score = 100 * ((1 - weight) * coverage + weight * semantic_scaled)
    mandatory_met = all(m.matched for m in matches if m.mandatory and m.kind != "work_authorization")
    return MatchOutput(
        score=round(score, 1),
        coverage_score=round(coverage * 100, 1),
        semantic_similarity=round(semantic, 3),
        mandatory_met=mandatory_met,
        matches=matches,
    )


class MatchingAgent(BaseAgent[MatchInput, MatchOutput]):
    name = AgentName.MATCHING

    def summarize_input(self, payload: MatchInput) -> dict:
        return payload.summarize()

    def execute(self, ctx: AgentContext, payload: MatchInput, state: RunState) -> MatchOutput:
        return compute_match(payload)
