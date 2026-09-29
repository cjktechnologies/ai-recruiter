from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.domain.enums import (
    ApplicationStage,
    ApplicationStatus,
    ApprovalStatus,
    AssessmentKind,
    AssessmentResultStatus,
    EvaluationDecision,
    InterviewKind,
    InterviewStatus,
    OfferStatus,
    QuestionKind,
    Recommendation,
    ReviewStatus,
    VerificationStatus,
)
from app.schemas.common import ORM, Timestamped


# --- Applications -----------------------------------------------------------------
class ApplicationIn(BaseModel):
    job_id: uuid.UUID
    candidate_id: uuid.UUID
    source: str = "sourced"
    cover_letter: str | None = Field(default=None, max_length=20000)
    screening_answers: dict[str, bool | str] = Field(default_factory=dict)


class ApplicationOut(Timestamped):
    job_id: uuid.UUID
    candidate_id: uuid.UUID
    stage: ApplicationStage
    status: ApplicationStatus
    source: str
    applied_at: datetime
    stage_changed_at: datetime
    match_score: float | None
    rejection_reason: str | None
    recruiter_id: uuid.UUID | None
    candidate_name: str | None = None
    job_title: str | None = None


class StageHistoryOut(ORM):
    id: uuid.UUID
    from_stage: ApplicationStage | None
    to_stage: ApplicationStage
    changed_by_id: uuid.UUID | None
    actor_type: str
    reason: str | None
    changed_at: datetime


class ApplicationDetail(ApplicationOut):
    screening_answers: dict
    cover_letter: str | None
    history: list[StageHistoryOut] = Field(default_factory=list)
    workflow: dict | None = None


class MoveIn(BaseModel):
    to_stage: ApplicationStage
    reason: str | None = Field(default=None, max_length=2000)


class RejectIn(BaseModel):
    reason: str = Field(min_length=2, max_length=300)
    notify_candidate: bool = True


# --- Screening --------------------------------------------------------------------
class ScreeningOut(Timestamped):
    application_id: uuid.UUID
    rule_results: list[dict]
    eligible: bool
    score: float
    facts: list[dict]
    interpretations: list[dict]
    summary: str
    recommendation: Recommendation
    review_status: ReviewStatus
    reviewed_by_id: uuid.UUID | None
    reviewed_at: datetime | None
    reviewer_decision: str | None
    override_reason: str | None
    agent_execution_id: uuid.UUID | None


class ScreeningReviewIn(BaseModel):
    decision: str = Field(pattern="^(advance|reject|hold)$")
    next_stage: ApplicationStage | None = Field(default=None, description="assessment or interview when advancing")
    override_reason: str | None = Field(default=None, max_length=4000)
    rejection_reason: str | None = None


# --- Assessments ------------------------------------------------------------------
class QuestionIn(BaseModel):
    kind: QuestionKind
    prompt: str = Field(min_length=3, max_length=10000)
    options: list[str] = Field(default_factory=list, max_length=20)
    correct_answer: dict | None = None
    rubric: str | None = None
    competency: str | None = None
    difficulty: str = Field(default="medium", pattern="^(easy|medium|hard)$")
    points: float = Field(default=1, gt=0, le=100)
    tags: list[str] = Field(default_factory=list)


class QuestionOut(Timestamped):
    assessment_id: uuid.UUID | None
    kind: QuestionKind
    prompt: str
    options: list[str]
    correct_answer: dict | None
    rubric: str | None
    competency: str | None
    difficulty: str
    points: float
    position: int
    tags: list[str]


class CandidateQuestionOut(BaseModel):
    id: uuid.UUID
    kind: QuestionKind
    prompt: str
    options: list[str]
    points: float


class AssessmentIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    kind: AssessmentKind
    job_id: uuid.UUID | None = None
    instructions: str | None = None
    duration_minutes: int = Field(default=45, ge=5, le=480)
    passing_score: float = Field(default=60, ge=0, le=100)
    questions: list[QuestionIn] = Field(default_factory=list)
    bank_question_ids: list[uuid.UUID] = Field(default_factory=list)


class AssessmentOut(Timestamped):
    job_id: uuid.UUID | None
    title: str
    kind: AssessmentKind
    instructions: str | None
    duration_minutes: int
    passing_score: float
    is_active: bool
    questions: list[QuestionOut]


class GenerateAssessmentIn(BaseModel):
    job_id: uuid.UUID
    title: str | None = None
    kind: AssessmentKind = AssessmentKind.TECHNICAL
    max_questions: int = Field(default=10, ge=1, le=50)


class InviteAssessmentIn(BaseModel):
    assessment_id: uuid.UUID
    expires_in_days: int = Field(default=7, ge=1, le=30)


class AssessmentResultOut(Timestamped):
    assessment_id: uuid.UUID
    application_id: uuid.UUID
    status: AssessmentResultStatus
    invited_at: datetime
    expires_at: datetime
    submitted_at: datetime | None
    answers: dict
    question_scores: dict
    score: float | None
    max_score: float | None
    percentage: float | None
    passed: bool | None
    competency_scores: dict
    candidate_feedback: str | None


class InviteOut(BaseModel):
    result: AssessmentResultOut
    candidate_link: str


class ManualScoreIn(BaseModel):
    question_scores: dict[str, float]
    candidate_feedback: str | None = None


class PublicAssessmentOut(BaseModel):
    title: str
    instructions: str | None
    duration_minutes: int
    expires_at: datetime
    status: AssessmentResultStatus
    questions: list[CandidateQuestionOut]


class SubmitAnswersIn(BaseModel):
    answers: dict[str, str | list[str] | float | int | None]


# --- Interviews -------------------------------------------------------------------
class InterviewTemplateIn(BaseModel):
    name: str
    kind: InterviewKind
    duration_minutes: int = Field(default=60, ge=10, le=480)
    competencies: list[dict] = Field(default_factory=list)
    questions: list[dict] = Field(default_factory=list)


class InterviewTemplateOut(Timestamped):
    name: str
    kind: InterviewKind
    duration_minutes: int
    competencies: list[dict]
    questions: list[dict]


class SlotRequestIn(BaseModel):
    interviewer_ids: list[uuid.UUID] = Field(min_length=1, max_length=10)
    duration_minutes: int = Field(default=60, ge=15, le=480)
    search_days: int = Field(default=10, ge=1, le=30)
    candidate_windows: list[dict] = Field(default_factory=list)
    candidate_timezone: str = "UTC"


class SlotOut(BaseModel):
    start: datetime
    end: datetime
    score: float


class InterviewIn(BaseModel):
    kind: InterviewKind
    template_id: uuid.UUID | None = None
    scheduled_start: datetime
    scheduled_end: datetime
    timezone: str = "UTC"
    location: str | None = None
    meeting_url: str | None = None
    interviewer_ids: list[uuid.UUID] = Field(min_length=1, max_length=10)
    lead_interviewer_id: uuid.UUID | None = None
    notify_candidate: bool = True
    create_calendar_event: bool = True


class InterviewerOut(ORM):
    user_id: uuid.UUID
    role: str
    response_status: str


class InterviewOut(Timestamped):
    application_id: uuid.UUID
    template_id: uuid.UUID | None
    kind: InterviewKind
    round: int
    status: InterviewStatus
    scheduled_start: datetime
    scheduled_end: datetime
    timezone: str
    location: str | None
    meeting_url: str | None
    calendar_provider: str | None
    calendar_event_id: str | None
    ai_summary: dict | None
    notes: str | None
    interviewers: list[InterviewerOut]
    candidate_name: str | None = None
    job_title: str | None = None


class InterviewUpdate(BaseModel):
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    location: str | None = None
    meeting_url: str | None = None
    notes: str | None = None


class CancelIn(BaseModel):
    reason: str = Field(min_length=2, max_length=300)


class TranscriptIn(BaseModel):
    transcript: str = Field(min_length=20, max_length=500000)
    consent_confirmed: bool = Field(description="Candidate consented to recording/transcription")


class RatingIn(BaseModel):
    competency: str
    rating: int = Field(ge=1, le=5)
    evidence: str | None = Field(default=None, max_length=4000)


class ScorecardIn(BaseModel):
    ratings: list[RatingIn] = Field(default_factory=list)
    overall_rating: float = Field(ge=1, le=5)
    recommendation: Recommendation
    strengths: str | None = None
    concerns: str | None = None
    notes: str | None = None


class ScorecardOut(Timestamped):
    interview_id: uuid.UUID
    interviewer_id: uuid.UUID
    ratings: list[dict]
    overall_rating: float | None
    recommendation: Recommendation | None
    strengths: str | None
    concerns: str | None
    notes: str | None
    submitted_at: datetime | None


# --- Evaluation / selection / verification -----------------------------------------
class EvaluationOut(Timestamped):
    application_id: uuid.UUID
    evidence: dict
    competency_matrix: dict
    overall_score: float | None
    ai_recommendation: Recommendation | None
    ai_rationale: str | None
    risks: list[str]
    decision: EvaluationDecision | None
    decided_by_id: uuid.UUID | None
    decided_at: datetime | None
    decision_rationale: str | None


class EvaluationDecisionIn(BaseModel):
    decision: EvaluationDecision
    rationale: str = Field(min_length=5, max_length=4000)


class SelectionDecisionIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    comment: str | None = None
    skip_verification: bool = False


class ReferenceIn(BaseModel):
    referee_name: str = Field(min_length=2, max_length=200)
    referee_email: str = Field(max_length=320)
    referee_phone: str | None = None
    relationship_to_candidate: str = Field(max_length=120)
    company: str | None = None
    send_request: bool = True


class ReferenceOut(Timestamped):
    application_id: uuid.UUID
    referee_name: str
    referee_email: str
    relationship_to_candidate: str
    company: str | None
    status: VerificationStatus
    questionnaire: list[dict]
    responses: dict
    requested_at: datetime
    completed_at: datetime | None


class ReferenceResponseIn(BaseModel):
    responses: dict[str, str | int | bool]
    decline: bool = False


class BackgroundCheckIn(BaseModel):
    provider: str = Field(default="manual", max_length=80)
    check_types: list[str] = Field(default_factory=lambda: ["identity", "employment", "criminal"])
    consent_confirmed: bool


class BackgroundCheckUpdate(BaseModel):
    status: VerificationStatus
    result: str | None = Field(default=None, pattern="^(clear|consider|adverse)$")
    result_detail: dict = Field(default_factory=dict)


class BackgroundCheckOut(Timestamped):
    application_id: uuid.UUID
    provider: str
    check_types: list[str]
    status: VerificationStatus
    external_id: str | None
    consent_obtained_at: datetime | None
    result: str | None
    result_detail: dict
    requested_at: datetime
    completed_at: datetime | None


# --- Offers -------------------------------------------------------------------------
class OfferDraftIn(BaseModel):
    base_salary: Decimal | None = Field(default=None, gt=0, description="Override the agent's proposal")
    start_date: date | None = None
    expires_in_days: int = Field(default=7, ge=1, le=60)
    equity: str | None = None


class OfferUpdate(BaseModel):
    base_salary: Decimal | None = Field(default=None, gt=0)
    bonus_pct: float | None = Field(default=None, ge=0, le=200)
    equity: str | None = None
    benefits: list[str] | None = None
    start_date: date | None = None
    expires_at: datetime | None = None
    letter_body: str | None = Field(default=None, max_length=50000)


class OfferApprovalOut(ORM):
    id: uuid.UUID
    step_order: int
    approver_role: str
    status: ApprovalStatus
    decided_by_id: uuid.UUID | None
    decided_at: datetime | None
    comment: str | None


class OfferOut(Timestamped):
    application_id: uuid.UUID
    version: int
    status: OfferStatus
    job_title: str
    base_salary: Decimal
    currency: str
    pay_frequency: str
    bonus_pct: float | None
    equity: str | None
    benefits: list[str]
    start_date: date | None
    expires_at: datetime | None
    compensation_band_id: uuid.UUID | None
    within_band: bool | None
    letter_body: str | None
    sent_at: datetime | None
    responded_at: datetime | None
    decline_reason: str | None
    approvals: list[OfferApprovalOut]


class OfferSendOut(BaseModel):
    offer: OfferOut
    candidate_link: str


class OfferResponseIn(BaseModel):
    accept: bool
    reason: str | None = Field(default=None, max_length=2000)


class PublicOfferOut(BaseModel):
    company: str
    job_title: str
    base_salary: Decimal
    currency: str
    bonus_pct: float | None
    benefits: list[str]
    start_date: date | None
    expires_at: datetime | None
    letter_body: str | None
    status: OfferStatus


# --- Onboarding -----------------------------------------------------------------------
class OnboardingTaskOut(Timestamped):
    application_id: uuid.UUID
    title: str
    description: str | None
    category: str
    status: str
    assignee_id: uuid.UUID | None
    due_date: date | None
    completed_at: datetime | None
    external_ref: str | None


class OnboardingTaskUpdate(BaseModel):
    status: str | None = Field(default=None, pattern="^(pending|in_progress|done|blocked)$")
    assignee_id: uuid.UUID | None = None
    due_date: date | None = None


class HandoffOut(Timestamped):
    application_id: uuid.UUID
    offer_id: uuid.UUID
    status: str
    hris_employee_id: str | None
    payload: dict
    last_error: str | None
    sent_at: datetime | None
