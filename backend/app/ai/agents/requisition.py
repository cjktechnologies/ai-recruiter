"""Recruitment Requisition Agent: validates hiring requests before they enter approval."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from pydantic import BaseModel, Field

from app.ai.agents.base import AgentContext, BaseAgent, RunState
from app.ai.agents.job_description import find_exclusionary_language
from app.domain.enums import AgentName


class RequisitionInput(BaseModel):
    title: str
    justification: str
    headcount: int
    employment_type: str
    job_level: str | None = None
    department: str | None = None
    location: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    min_years_experience: int | None = None
    budget_min: Decimal | None = None
    budget_max: Decimal | None = None
    currency: str = "USD"
    target_start_date: date | None = None
    band_min: Decimal | None = None
    band_max: Decimal | None = None
    today: date = Field(default_factory=date.today)


class Issue(BaseModel):
    severity: str  # error|warning|info
    field: str
    message: str


class RequisitionOutput(BaseModel):
    valid: bool
    completeness: float = Field(ge=0, le=1)
    issues: list[Issue]
    suggestions: list[str]
    approval_route: list[str]


class LLMRequisitionReview(BaseModel):
    suggestions: list[str]
    risks: list[str]


class RequisitionAgent(BaseAgent[RequisitionInput, RequisitionOutput]):
    name = AgentName.REQUISITION
    prompt_key = "requisition"

    def execute(self, ctx: AgentContext, p: RequisitionInput, state: RunState) -> RequisitionOutput:
        issues: list[Issue] = []
        if len(p.justification.split()) < 15:
            issues.append(
                Issue(
                    severity="error",
                    field="justification",
                    message="Business justification is too brief (min ~15 words).",
                )
            )
        if not p.required_skills:
            issues.append(Issue(severity="error", field="required_skills", message="List at least one required skill."))
        if len(p.required_skills) > 12:
            issues.append(
                Issue(
                    severity="warning",
                    field="required_skills",
                    message="More than 12 must-have skills narrows the pool; move some to preferred.",
                )
            )
        if not p.responsibilities:
            issues.append(Issue(severity="warning", field="responsibilities", message="Add key responsibilities."))
        if p.budget_min is None or p.budget_max is None:
            issues.append(Issue(severity="error", field="budget", message="Salary budget range is required."))
        elif (
            p.band_min is not None
            and p.band_max is not None
            and (p.budget_min < p.band_min or p.budget_max > p.band_max)
        ):
            issues.append(
                Issue(
                    severity="warning",
                    field="budget",
                    message=f"Budget {p.budget_min}-{p.budget_max} is outside the approved band "
                    f"{p.band_min}-{p.band_max}; finance approval will be required.",
                )
            )
        if p.target_start_date and p.target_start_date < p.today + timedelta(days=21):
            issues.append(
                Issue(
                    severity="warning",
                    field="target_start_date",
                    message="Target start is less than 3 weeks away; typical time-to-hire is 30-45 days.",
                )
            )
        if p.min_years_experience and p.min_years_experience > 15:
            issues.append(
                Issue(
                    severity="warning",
                    field="min_years_experience",
                    message="Very high experience minimums can be exclusionary; consider competencies.",
                )
            )
        text = " ".join([p.title, p.justification, *p.responsibilities, *p.required_skills])
        for term, alt in find_exclusionary_language(text):
            issues.append(Issue(severity="warning", field="language", message=f"Consider replacing '{term}' ({alt})."))
        fields = [
            p.title,
            p.justification,
            p.required_skills,
            p.responsibilities,
            p.budget_min,
            p.budget_max,
            p.location,
            p.job_level,
            p.target_start_date,
            p.department,
        ]
        completeness = sum(1 for f in fields if f) / len(fields)
        route = ["hiring_manager"]
        if any(i.field == "budget" and i.severity == "warning" for i in issues) or p.headcount > 3:
            route.append("finance_approver")
        route.append("hr_manager")
        suggestions = [i.message for i in issues if i.severity != "info"]
        llm = self.ask_llm(state, schema=LLMRequisitionReview, user=p.model_dump_json(exclude={"today"}))
        if llm:
            suggestions += llm.suggestions
            issues += [Issue(severity="info", field="ai_review", message=r) for r in llm.risks]
        return RequisitionOutput(
            valid=not any(i.severity == "error" for i in issues),
            completeness=round(completeness, 2),
            issues=issues,
            suggestions=suggestions,
            approval_route=route,
        )
