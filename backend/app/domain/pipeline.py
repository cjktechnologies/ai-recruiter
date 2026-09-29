"""Application pipeline state machine and human-in-the-loop gates.

The allowed transitions encode the core flow:
Applied → Screening → Screened (human review) → Assessment → Interview → Evaluation →
Selection (approval) → Verification → Offer → Hired.

Some transitions are *gated*: they may only be performed by a human with the specified
permission, never by an AI agent. The orchestrator consults ``requires_human`` before acting.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums import ApplicationStage as S

TERMINAL: frozenset[S] = frozenset({S.HIRED, S.REJECTED, S.WITHDRAWN})

TRANSITIONS: dict[S, frozenset[S]] = {
    S.APPLIED: frozenset({S.SCREENING}),
    S.SCREENING: frozenset({S.SCREENED}),
    S.SCREENED: frozenset({S.ASSESSMENT, S.INTERVIEW}),
    S.ASSESSMENT: frozenset({S.INTERVIEW, S.EVALUATION}),
    S.INTERVIEW: frozenset({S.EVALUATION, S.INTERVIEW}),
    S.EVALUATION: frozenset({S.SELECTION, S.INTERVIEW}),
    S.SELECTION: frozenset({S.VERIFICATION, S.OFFER}),
    S.VERIFICATION: frozenset({S.OFFER}),
    S.OFFER: frozenset({S.HIRED}),
    S.HIRED: frozenset(),
    S.REJECTED: frozenset(),
    S.WITHDRAWN: frozenset(),
}

ORDER: tuple[S, ...] = (
    S.APPLIED, S.SCREENING, S.SCREENED, S.ASSESSMENT, S.INTERVIEW, S.EVALUATION,
    S.SELECTION, S.VERIFICATION, S.OFFER, S.HIRED,
)


@dataclass(frozen=True)
class Gate:
    permission: str
    reason: str


# Transitions (from, to) that are consequential and therefore human-only.
HUMAN_GATES: dict[tuple[S, S], Gate] = {
    (S.SCREENED, S.ASSESSMENT): Gate("screening:review", "Recruiter must review AI screening"),
    (S.SCREENED, S.INTERVIEW): Gate("screening:review", "Recruiter must review AI screening"),
    (S.EVALUATION, S.SELECTION): Gate("evaluations:decide", "Hiring manager decides on selection"),
    (S.SELECTION, S.VERIFICATION): Gate("selection:approve", "Selection must be approved"),
    (S.SELECTION, S.OFFER): Gate("selection:approve", "Selection must be approved"),
    (S.OFFER, S.HIRED): Gate("offers:read", "Candidate acceptance recorded by a human"),
}


def can_transition(current: S, target: S) -> bool:
    if current in TERMINAL:
        return False
    if target in (S.REJECTED, S.WITHDRAWN):
        return True
    return target in TRANSITIONS[current]


def gate_for(current: S, target: S) -> Gate | None:
    if target == S.REJECTED:
        return Gate("applications:reject", "Rejections are always human decisions")
    return HUMAN_GATES.get((current, target))


def stage_index(stage: S) -> int:
    return ORDER.index(stage) if stage in ORDER else -1
