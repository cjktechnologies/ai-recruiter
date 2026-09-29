"""Job Description Agent: creates/optimizes JDs and adverts with inclusive-language checks."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.ai.agents.base import AgentContext, BaseAgent, RunState
from app.ai.guardrails import validate_ai_rationale
from app.domain.enums import AgentName

EXCLUSIONARY: dict[str, str] = {
    "rockstar": "use 'skilled' or 'expert'",
    "ninja": "use 'expert'",
    "guru": "use 'specialist'",
    "young": "age-related; describe the work environment instead",
    "energetic": "can imply age; use 'motivated'",
    "digital native": "age-related; describe the required digital skills",
    "recent graduate": "age-proxy; use 'early-career' or state the skill level",
    "native speaker": "use 'fluent in'",
    "manpower": "use 'workforce' or 'staff'",
    "salesman": "use 'salesperson'",
    "chairman": "use 'chair'",
    "he/she": "use 'they'",
    "he will": "use 'you will'",
    "she will": "use 'you will'",
    "aggressive": "use 'ambitious' or 'proactive'",
    "dominant": "use 'leading'",
    "able-bodied": "describe the actual physical requirement",
    "culture fit": "use 'values alignment' with defined values",
}


def find_exclusionary_language(text: str) -> list[tuple[str, str]]:
    found = []
    lowered = text.lower()
    for term, alt in EXCLUSIONARY.items():
        if re.search(rf"(?<![a-z]){re.escape(term)}(?![a-z])", lowered):
            found.append((term, alt))
    return found


class JDInput(BaseModel):
    company_name: str
    title: str
    department: str | None = None
    location: str | None = None
    remote_policy: str = "onsite"
    employment_type: str = "full_time"
    summary: str | None = None
    responsibilities: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    min_years_experience: int | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    currency: str = "USD"
    show_salary: bool = True
    benefits: list[str] = Field(default_factory=list)
    existing_description: str | None = None


class SuggestedRequirement(BaseModel):
    kind: str
    name: str
    is_mandatory: bool
    weight: float
    min_years: float | None = None


class JDOutput(BaseModel):
    description: str
    advertisement: str
    requirements: list[SuggestedRequirement]
    inclusive_language_issues: list[str]
    ai_generated: bool


class LLMJD(BaseModel):
    description: str
    advertisement: str


class JobDescriptionAgent(BaseAgent[JDInput, JDOutput]):
    name = AgentName.JOB_DESCRIPTION
    prompt_key = "job_description"

    def execute(self, ctx: AgentContext, p: JDInput, state: RunState) -> JDOutput:
        reqs = [SuggestedRequirement(kind="skill", name=s, is_mandatory=True, weight=2.0) for s in p.required_skills]
        reqs += [SuggestedRequirement(kind="skill", name=s, is_mandatory=False, weight=1.0) for s in p.preferred_skills]
        if p.min_years_experience:
            reqs.append(SuggestedRequirement(kind="experience", name="Professional experience", is_mandatory=False,
                                             weight=1.5, min_years=p.min_years_experience))
        description, advert = self._template(p)
        ai_generated = False
        llm = self.ask_llm(state, schema=LLMJD, user=p.model_dump_json())
        if llm:
            flags = validate_ai_rationale(llm.description + " " + llm.advertisement)
            # Words like 'disability' may legitimately appear in EEO statements; flag, don't block.
            state.flags.extend(f"review:{f}" for f in flags)
            description, advert, ai_generated = llm.description, llm.advertisement, True
        issues = [f"'{t}': {a}" for t, a in find_exclusionary_language(description + " " + advert)]
        return JDOutput(description=description, advertisement=advert, requirements=reqs,
                        inclusive_language_issues=issues, ai_generated=ai_generated)

    @staticmethod
    def _template(p: JDInput) -> tuple[str, str]:
        work = {"remote": "Remote", "hybrid": "Hybrid", "onsite": "On-site"}.get(p.remote_policy, p.remote_policy)
        where = f"{work}{' — ' + p.location if p.location else ''}"
        salary = ""
        if p.show_salary and p.salary_min and p.salary_max:
            salary = f"\n## Compensation\n{p.currency} {p.salary_min:,.0f} – {p.salary_max:,.0f} per year, plus benefits.\n"
        resp = "\n".join(f"- {r}" for r in p.responsibilities) or "- Details to be discussed with the hiring team."
        must = "\n".join(f"- {s}" for s in p.required_skills) or "- See role summary"
        nice = "\n".join(f"- {s}" for s in p.preferred_skills)
        exp = f"- {p.min_years_experience}+ years of relevant experience (or equivalent demonstrated skill)\n" \
            if p.min_years_experience else ""
        benefits = "\n".join(f"- {b}" for b in p.benefits)
        summary = p.summary or (
            f"{p.company_name} is hiring a {p.title}"
            f"{' in our ' + p.department + ' team' if p.department else ''}. You will make a direct impact and "
            "work with a collaborative, supportive team."
        )
        description = (
            f"# {p.title}\n\n**Location:** {where}  \n**Employment type:** {p.employment_type.replace('_', ' ')}\n\n"
            f"## About the role\n{summary}\n\n## What you will do\n{resp}\n\n"
            f"## What you will bring\n{exp}{must}\n"
            + (f"\n## Nice to have\n{nice}\n" if nice else "")
            + salary
            + (f"\n## Benefits\n{benefits}\n" if benefits else "")
            + f"\n## Equal opportunity\n{p.company_name} is an equal-opportunity employer. We welcome applicants "
            "of all backgrounds and provide reasonable accommodations throughout the hiring process on request.\n"
        )
        advert = (
            f"{p.company_name} is hiring: {p.title} ({where}). "
            f"Key skills: {', '.join(p.required_skills[:5]) or 'see description'}. "
            + (f"Salary {p.currency} {p.salary_min:,.0f}–{p.salary_max:,.0f}. " if salary else "")
            + "Apply today — we review every application."
        )
        return description, advert
