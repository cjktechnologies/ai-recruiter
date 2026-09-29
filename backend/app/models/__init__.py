"""Import all models so SQLAlchemy metadata (and Alembic autogenerate) sees every table."""

from app.models.assessments import Assessment, AssessmentQuestion, AssessmentResult
from app.models.candidates import (
    Candidate,
    CandidateDocument,
    CandidateNote,
    CandidateSkill,
    ConsentRecord,
    EEOResponse,
    Skill,
)
from app.models.comms import Communication, Notification
from app.models.governance import (
    AIAgentExecution,
    AIRecommendation,
    AuditLog,
    IdempotencyKey,
    Integration,
    WorkflowRun,
)
from app.models.interviews import Interview, Interviewer, InterviewScorecard, InterviewTemplate
from app.models.onboarding import OnboardingHandoff, OnboardingTask
from app.models.org import Department, Organization, RefreshToken, RoleDef, User, user_roles
from app.models.pipeline import Application, ApplicationStageHistory, ScreeningResult
from app.models.recruitment import (
    ApprovalStep,
    ApprovalWorkflow,
    CompensationBand,
    HiringRequisition,
    Job,
    JobRequirement,
    TalentPool,
    talent_pool_members,
)
from app.models.selection import (
    BackgroundCheck,
    CandidateEvaluation,
    CandidateReference,
    Offer,
    OfferApproval,
)

__all__ = [
    "AIAgentExecution",
    "AIRecommendation",
    "Application",
    "ApplicationStageHistory",
    "ApprovalStep",
    "ApprovalWorkflow",
    "Assessment",
    "AssessmentQuestion",
    "AssessmentResult",
    "AuditLog",
    "BackgroundCheck",
    "Candidate",
    "CandidateDocument",
    "CandidateEvaluation",
    "CandidateNote",
    "CandidateReference",
    "CandidateSkill",
    "Communication",
    "CompensationBand",
    "ConsentRecord",
    "Department",
    "EEOResponse",
    "HiringRequisition",
    "IdempotencyKey",
    "Integration",
    "Interview",
    "InterviewScorecard",
    "InterviewTemplate",
    "Interviewer",
    "Job",
    "JobRequirement",
    "Notification",
    "Offer",
    "OfferApproval",
    "OnboardingHandoff",
    "OnboardingTask",
    "Organization",
    "RefreshToken",
    "RoleDef",
    "ScreeningResult",
    "Skill",
    "TalentPool",
    "User",
    "WorkflowRun",
    "talent_pool_members",
    "user_roles",
]
