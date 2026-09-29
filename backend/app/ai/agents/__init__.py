"""Agent registry."""

from app.ai.agents.analytics import AnalyticsAgent
from app.ai.agents.assessment import AssessmentBuilderAgent, AssessmentScoringAgent
from app.ai.agents.communication import CommunicationAgent
from app.ai.agents.evaluation import EvaluationAgent
from app.ai.agents.interview_assistant import InterviewAssistantAgent
from app.ai.agents.job_description import JobDescriptionAgent
from app.ai.agents.matching import MatchingAgent
from app.ai.agents.offer import OfferAgent
from app.ai.agents.onboarding import OnboardingAgent
from app.ai.agents.requisition import RequisitionAgent
from app.ai.agents.scheduling import SchedulingAgent
from app.ai.agents.screening import ScreeningAgent
from app.ai.agents.sourcing import SourcingAgent

AGENT_CATALOG = [
    ("requisition", "Recruitment Requisition Agent", "Validates and processes hiring requests", RequisitionAgent),
    ("job_description", "Job Description Agent", "Creates and optimizes JDs and adverts", JobDescriptionAgent),
    ("sourcing", "Talent Sourcing Agent", "Ranks consented talent-pool candidates; approved channels", SourcingAgent),
    ("screening", "Candidate Screening Agent", "Rule checks + evidence-based screening summaries", ScreeningAgent),
    ("matching", "Candidate Matching Agent", "Explainable candidate/job matching", MatchingAgent),
    ("communication", "Candidate Communication Agent", "FAQs, acknowledgements, status updates", CommunicationAgent),
    ("assessment", "Assessment Agent", "Builds and scores structured assessments", AssessmentScoringAgent),
    ("scheduling", "Interview Scheduling Agent", "Coordinates availability and calendar events", SchedulingAgent),
    ("interview_assistant", "Interview Assistant Agent", "Transcript summaries and competency evidence",
     InterviewAssistantAgent),
    ("evaluation", "Candidate Evaluation Agent", "Consolidates structured evidence", EvaluationAgent),
    ("offer", "Offer Agent", "Drafts offers within approved compensation", OfferAgent),
    ("analytics", "Recruitment Analytics Agent", "Funnel, SLA, source and fairness insights", AnalyticsAgent),
    ("onboarding", "Onboarding Handoff Agent", "HRIS handoff and preboarding checklist", OnboardingAgent),
]

__all__ = [
    "AGENT_CATALOG", "AnalyticsAgent", "AssessmentBuilderAgent", "AssessmentScoringAgent", "CommunicationAgent",
    "EvaluationAgent", "InterviewAssistantAgent", "JobDescriptionAgent", "MatchingAgent", "OfferAgent",
    "OnboardingAgent", "RequisitionAgent", "SchedulingAgent", "ScreeningAgent", "SourcingAgent",
]
