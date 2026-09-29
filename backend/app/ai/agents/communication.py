"""Candidate Communication Agent: templated notifications and a grounded recruitment FAQ chatbot."""

from __future__ import annotations

import re
from string import Template

from pydantic import BaseModel, Field

from app.ai.agents.base import AgentContext, BaseAgent, RunState
from app.ai.guardrails import sanitize_untrusted, wrap_untrusted
from app.domain.enums import AgentName

TEMPLATES: dict[str, tuple[str, str]] = {
    "application_received": (
        "We received your application for $job_title",
        "Hi $first_name,\n\nThank you for applying for the $job_title role at $company. Our team reviews every "
        "application carefully and we will update you on next steps. You can check your status any time in the "
        "candidate portal.\n\nKind regards,\n$company Recruitment",
    ),
    "status_update": (
        "Update on your application for $job_title",
        "Hi $first_name,\n\nYour application for $job_title has moved to the $stage stage. $extra\n\n"
        "Kind regards,\n$company Recruitment",
    ),
    "assessment_invitation": (
        "Assessment for $job_title",
        "Hi $first_name,\n\nAs the next step for $job_title, please complete the '$assessment_title' assessment "
        "($duration minutes) before $deadline:\n$link\n\nIf you need an accommodation, just reply to this email.\n\n"
        "Kind regards,\n$company Recruitment",
    ),
    "interview_invitation": (
        "Interview invitation — $job_title",
        "Hi $first_name,\n\nWe'd like to invite you to a $interview_kind interview for $job_title on $when "
        "($timezone).\n$location\n\nPlease let us know if you need to reschedule or require any accommodation.\n\n"
        "Kind regards,\n$company Recruitment",
    ),
    "interview_reminder": (
        "Reminder: interview for $job_title",
        "Hi $first_name,\n\nThis is a reminder of your interview for $job_title on $when ($timezone).\n$location\n\n"
        "Good luck!\n$company Recruitment",
    ),
    "rejection": (
        "Your application for $job_title",
        "Hi $first_name,\n\nThank you for your interest in $job_title and for the time you invested. After careful "
        "consideration, we will not be moving forward with your application at this time. With your consent we "
        "will keep your profile for future opportunities.\n\nKind regards,\n$company Recruitment",
    ),
    "offer_sent": (
        "Your offer from $company",
        "Hi $first_name,\n\nWe're delighted to offer you the $job_title role. Please review and respond to your "
        "offer here: $link\nThe offer is valid until $deadline.\n\nKind regards,\n$company Recruitment",
    ),
    "reference_request": (
        "Reference request for $candidate_name",
        "Hello $referee_name,\n\n$candidate_name has listed you as a referee for the $job_title role at $company. "
        "Please share your feedback here: $link\n\nThank you,\n$company Recruitment",
    ),
    "welcome": (
        "Welcome to $company!",
        "Hi $first_name,\n\nWelcome aboard! Your start date is $start_date. You'll receive preboarding tasks and "
        "equipment details shortly.\n\n$company People Team",
    ),
}


def render_template(key: str, variables: dict[str, object]) -> tuple[str, str]:
    subject, body = TEMPLATES[key]
    safe = {k: str(v) for k, v in variables.items()}
    return Template(subject).safe_substitute(safe), Template(body).safe_substitute(safe)


DEFAULT_FAQ: list[dict[str, str]] = [
    {"q": "How long does the hiring process take?",
     "a": "Most processes take 3-6 weeks from application to offer, depending on the role and interview schedules."},
    {"q": "Can I apply for more than one role?", "a": "Yes, you may apply for any roles that match your skills."},
    {"q": "Do you provide accommodations?",
     "a": "Yes. Tell us what you need at any stage and we will arrange reasonable accommodations."},
    {"q": "How is AI used in the process?",
     "a": "AI helps us organise applications and summarise evidence. Every decision about your application is "
         "made by a person, and you can ask for a human review at any time."},
    {"q": "How do I withdraw or delete my data?",
     "a": "You can withdraw an application in the candidate portal or ask us to delete your data; we will "
         "confirm once completed."},
    {"q": "What is my application status?", "a": "Your current status is shown in the candidate portal."},
]


class ChatInput(BaseModel):
    question: str
    company: str
    candidate_first_name: str | None = None
    application_status: dict[str, str] | None = None  # {"job_title":..., "stage":...}
    faq: list[dict[str, str]] = Field(default_factory=lambda: list(DEFAULT_FAQ))


class ChatOutput(BaseModel):
    answer: str
    needs_human: bool
    sources: list[str]
    ai_generated: bool


class LLMChat(BaseModel):
    answer: str
    needs_human: bool
    security_notes: list[str]


_WORD = re.compile(r"[a-z]{3,}")
_STOP = {"the", "and", "for", "you", "your", "how", "what", "can", "does", "are", "with", "this", "that", "long"}


def _terms(s: str) -> set[str]:
    return {w for w in _WORD.findall(s.lower()) if w not in _STOP}


def retrieve_faq(question: str, faq: list[dict[str, str]], k: int = 3) -> list[tuple[float, dict[str, str]]]:
    q = _terms(question)
    scored = []
    for item in faq:
        t = _terms(item["q"] + " " + item["a"])
        overlap = len(q & t) / (len(q) or 1)
        scored.append((overlap, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for s in scored[:k] if s[0] > 0]


class CommunicationAgent(BaseAgent[ChatInput, ChatOutput]):
    name = AgentName.COMMUNICATION
    prompt_key = "communication"

    def execute(self, ctx: AgentContext, p: ChatInput, state: RunState) -> ChatOutput:
        clean = sanitize_untrusted(p.question, max_chars=2000)
        state.flags.extend(clean.flags)
        hits = retrieve_faq(clean.text, p.faq)
        status_q = bool(re.search(r"\b(status|update|progress|stage|hear back)\b", clean.text, re.I))
        if status_q and p.application_status:
            return ChatOutput(
                answer=f"Your application for {p.application_status.get('job_title')} is currently at the "
                       f"'{p.application_status.get('stage')}' stage. We'll contact you as soon as there is an update.",
                needs_human=False, sources=["application_status"], ai_generated=False,
            )
        if not clean.is_suspicious:
            kb = "\n".join(f"Q: {h['q']}\nA: {h['a']}" for _, h in hits) or "(no relevant entries)"
            llm = self.ask_llm(state, schema=LLMChat, user=(
                f"Company: {p.company}\nKnowledge base:\n{kb}\n\n"
                f"Candidate application status: {p.application_status or 'unknown'}\n\n"
                f"{wrap_untrusted('candidate_message', clean.text)}"
            ))
            if llm:
                if llm.security_notes:
                    state.flags.append("llm_reported_security_notes")
                return ChatOutput(answer=llm.answer, needs_human=llm.needs_human,
                                  sources=[h["q"] for _, h in hits], ai_generated=True)
        if hits and hits[0][0] >= 0.34 and not clean.is_suspicious:
            best = hits[0][1]
            return ChatOutput(answer=best["a"], needs_human=False, sources=[best["q"]], ai_generated=False)
        return ChatOutput(
            answer="Thanks for your question. I've passed it to a member of our recruitment team, who will get "
                   "back to you shortly.",
            needs_human=True, sources=[], ai_generated=False,
        )
