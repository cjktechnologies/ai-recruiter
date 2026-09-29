"""Offer Agent: drafts offers strictly within approved compensation parameters."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, Field

from app.ai.agents.base import AgentContext, BaseAgent, RunState
from app.domain.enums import AgentName


class Band(BaseModel):
    id: str | None = None
    min_salary: Decimal
    max_salary: Decimal
    currency: str
    max_bonus_pct: float = 0
    benefits: list[str] = Field(default_factory=list)


class OfferInput(BaseModel):
    company: str
    candidate_first_name: str
    job_title: str
    band: Band | None
    requisition_budget_max: Decimal | None = None
    evaluation_score: float | None = None  # 0-100
    requested_salary: Decimal | None = None  # recruiter override
    start_date: date | None = None
    expires_on: date | None = None


class OfferDraft(BaseModel):
    base_salary: Decimal
    currency: str
    bonus_pct: float
    benefits: list[str]
    within_band: bool
    requires_finance_approval: bool
    approval_chain: list[str]
    rationale: str
    letter_body: str
    ai_generated_letter: bool


class LLMOfferLetter(BaseModel):
    letter_body: str


def _round(v: Decimal) -> Decimal:
    return (v / 500).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * 500


class OfferAgent(BaseAgent[OfferInput, OfferDraft]):
    name = AgentName.OFFER
    prompt_key = "offer"

    def execute(self, ctx: AgentContext, p: OfferInput, state: RunState) -> OfferDraft:
        if p.band is None:
            if p.requested_salary is None:
                raise ValueError("No compensation band configured and no salary provided")
            salary, currency, within, bonus, benefits = p.requested_salary, "USD", False, 0.0, []
            rationale = "No approved band found; salary supplied by recruiter — finance approval required."
        else:
            b = p.band
            span = b.max_salary - b.min_salary
            # Position in band: 25th percentile baseline, up to 75th for strong evaluations.
            pos = Decimal("0.25") + Decimal(str(min(max((p.evaluation_score or 50) - 50, 0), 50) / 100))
            proposed = _round(b.min_salary + span * pos)
            if p.requisition_budget_max is not None:
                proposed = min(proposed, p.requisition_budget_max)
            salary = p.requested_salary if p.requested_salary is not None else proposed
            within = b.min_salary <= salary <= b.max_salary
            currency, benefits = b.currency, b.benefits
            bonus = b.max_bonus_pct if (p.evaluation_score or 0) >= 80 else round(b.max_bonus_pct / 2, 1)
            rationale = (
                f"Band {b.min_salary}-{b.max_salary} {b.currency}; positioned at {int(pos * 100)}th percentile based "
                f"on evaluation score {p.evaluation_score}."
                + ("" if within else " Proposed salary is OUTSIDE the band.")
            )
        over_budget = p.requisition_budget_max is not None and salary > p.requisition_budget_max
        needs_finance = (not within) or over_budget
        chain = ["hr_manager"] + (["finance_approver"] if needs_finance else []) + ["hiring_manager"]
        letter = self._letter(p, salary, currency, bonus, benefits)
        ai_letter = False
        llm = self.ask_llm(state, schema=LLMOfferLetter, user=(
            f"Company: {p.company}\nCandidate first name: {p.candidate_first_name}\nRole: {p.job_title}\n"
            f"Base salary: {currency} {salary}\nBonus: {bonus}%\nBenefits: {', '.join(benefits) or 'standard'}\n"
            f"Start date: {p.start_date or 'to be agreed'}\nOffer valid until: {p.expires_on or 'to be confirmed'}"
        ))
        if llm and str(salary) in llm.letter_body.replace(",", ""):
            letter, ai_letter = llm.letter_body, True
        elif llm:
            state.flags.append("llm_letter_rejected:figures_mismatch")
        return OfferDraft(
            base_salary=salary, currency=currency, bonus_pct=bonus, benefits=benefits, within_band=within,
            requires_finance_approval=needs_finance, approval_chain=chain, rationale=rationale,
            letter_body=letter, ai_generated_letter=ai_letter,
        )

    @staticmethod
    def _letter(p: OfferInput, salary: Decimal, currency: str, bonus: float, benefits: list[str]) -> str:
        ben = "".join(f"\n  - {b}" for b in benefits) or "\n  - Standard company benefits"
        return (
            f"Dear {p.candidate_first_name},\n\n"
            f"We are delighted to offer you the position of {p.job_title} at {p.company}.\n\n"
            f"Compensation:\n  - Base salary: {currency} {salary:,.2f} per year\n"
            + (f"  - Annual bonus target: {bonus}% of base salary\n" if bonus else "")
            + f"Benefits:{ben}\n\n"
            f"Proposed start date: {p.start_date.isoformat() if p.start_date else 'to be agreed'}.\n"
            f"This offer is valid until {p.expires_on.isoformat() if p.expires_on else 'the date indicated'} and is "
            "subject to satisfactory completion of reference and background checks where applicable.\n\n"
            f"We look forward to welcoming you to the team.\n\nSincerely,\n{p.company}"
        )
