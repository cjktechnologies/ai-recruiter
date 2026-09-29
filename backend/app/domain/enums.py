"""Domain enumerations shared by models, schemas and services."""

from __future__ import annotations

from enum import StrEnum


class RequisitionStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    ON_HOLD = "on_hold"
    FILLED = "filled"
    CANCELLED = "cancelled"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SKIPPED = "skipped"


class JobStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    PAUSED = "paused"
    CLOSED = "closed"


class EmploymentType(StrEnum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    TEMPORARY = "temporary"
    INTERNSHIP = "internship"


class RemotePolicy(StrEnum):
    ONSITE = "onsite"
    HYBRID = "hybrid"
    REMOTE = "remote"


class RequirementKind(StrEnum):
    SKILL = "skill"
    EXPERIENCE = "experience"
    EDUCATION = "education"
    CERTIFICATION = "certification"
    LANGUAGE = "language"
    LOCATION = "location"
    WORK_AUTHORIZATION = "work_authorization"


class ApplicationStage(StrEnum):
    APPLIED = "applied"
    SCREENING = "screening"
    SCREENED = "screened"
    ASSESSMENT = "assessment"
    INTERVIEW = "interview"
    EVALUATION = "evaluation"
    SELECTION = "selection"
    VERIFICATION = "verification"
    OFFER = "offer"
    HIRED = "hired"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class ApplicationStatus(StrEnum):
    ACTIVE = "active"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    HIRED = "hired"


class DocumentKind(StrEnum):
    CV = "cv"
    COVER_LETTER = "cover_letter"
    CERTIFICATE = "certificate"
    OTHER = "other"


class ScanStatus(StrEnum):
    PENDING = "pending"
    CLEAN = "clean"
    INFECTED = "infected"
    REJECTED = "rejected"
    ERROR = "error"


class ParseStatus(StrEnum):
    PENDING = "pending"
    PARSED = "parsed"
    FAILED = "failed"


class ReviewStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    ACCEPTED = "accepted"
    OVERRIDDEN = "overridden"
    REJECTED = "rejected"


class Recommendation(StrEnum):
    STRONG_YES = "strong_yes"
    YES = "yes"
    MAYBE = "maybe"
    NO = "no"
    STRONG_NO = "strong_no"


class AssessmentKind(StrEnum):
    TECHNICAL = "technical"
    COMPETENCY = "competency"
    COGNITIVE = "cognitive"
    LANGUAGE = "language"


class QuestionKind(StrEnum):
    SINGLE_CHOICE = "single_choice"
    MULTI_CHOICE = "multi_choice"
    SHORT_TEXT = "short_text"
    LONG_TEXT = "long_text"
    CODE = "code"
    RATING = "rating"


class AssessmentResultStatus(StrEnum):
    INVITED = "invited"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    SCORED = "scored"
    EXPIRED = "expired"


class InterviewKind(StrEnum):
    PHONE_SCREEN = "phone_screen"
    VIDEO = "video"
    ONSITE = "onsite"
    TECHNICAL = "technical"
    PANEL = "panel"
    FINAL = "final"


class InterviewStatus(StrEnum):
    PROPOSED = "proposed"
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class EvaluationDecision(StrEnum):
    ADVANCE_TO_SELECTION = "advance_to_selection"
    HOLD = "hold"
    REJECT = "reject"


class VerificationStatus(StrEnum):
    REQUESTED = "requested"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    DECLINED = "declined"


class OfferStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    SENT = "sent"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    WITHDRAWN = "withdrawn"
    EXPIRED = "expired"


class OnboardingTaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"


class OnboardingCategory(StrEnum):
    PREBOARDING = "preboarding"
    HR = "hr"
    IT = "it"
    FACILITIES = "facilities"
    PAYROLL = "payroll"
    TEAM = "team"


class Channel(StrEnum):
    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    CHAT = "chat"
    PORTAL = "portal"


class Direction(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class DeliveryStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"


class ActorType(StrEnum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"
    CANDIDATE = "candidate"


class AgentName(StrEnum):
    REQUISITION = "requisition"
    JOB_DESCRIPTION = "job_description"
    SOURCING = "sourcing"
    SCREENING = "screening"
    MATCHING = "matching"
    COMMUNICATION = "communication"
    ASSESSMENT = "assessment"
    SCHEDULING = "scheduling"
    INTERVIEW_ASSISTANT = "interview_assistant"
    EVALUATION = "evaluation"
    OFFER = "offer"
    ANALYTICS = "analytics"
    ONBOARDING = "onboarding"


class ExecutionStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class WorkflowStatus(StrEnum):
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class IntegrationKind(StrEnum):
    GOOGLE_CALENDAR = "google_calendar"
    MICROSOFT_GRAPH = "microsoft_graph"
    SMTP = "smtp"
    TWILIO = "twilio"
    HRIS_WEBHOOK = "hris_webhook"
    JOB_BOARD = "job_board"
    BACKGROUND_CHECK = "background_check"


class ConsentPurpose(StrEnum):
    RECRUITMENT_PROCESSING = "recruitment_processing"
    TALENT_POOL = "talent_pool"
    AI_ASSISTED_SCREENING = "ai_assisted_screening"
    INTERVIEW_RECORDING = "interview_recording"
    BACKGROUND_CHECK = "background_check"
