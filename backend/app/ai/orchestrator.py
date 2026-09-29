"""Recruitment Orchestrator.

A durable, event-driven state graph (equivalent to a LangGraph ``StateGraph`` with a Postgres
checkpointer and ``interrupt`` nodes). Each application has one ``WorkflowRun`` whose state is
checkpointed after every transition. Automated nodes invoke agents; human nodes *interrupt*
the graph (status ``waiting_human``) until a person acts through the API, which emits the event
that resumes the graph.

    intake ──► screening ──► [screening_review]* ──► assessment ──► interview ──► evaluation
                                                  └───────────────► interview ┘
    evaluation ──► [evaluation_decision]* ──► [selection_approval]* ──► verification ──► offer
    offer ──► [offer_approval]* ──► [offer_send]* ──► (candidate_response) ──► [onboarding_handoff]* ──► done

    * = human-in-the-loop interrupt. AI never performs these transitions itself.

Why not a library graph runtime: recruitment workflows last weeks, are resumed by HTTP events
from many users, and must be auditable row-by-row in the tenant's own database. A small,
explicit transition table persisted in ``workflow_runs`` gives the same semantics (nodes,
edges, checkpoints, interrupts) with no extra infrastructure, and every step is unit-tested.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.logging import get_logger, log_event
from app.core.principal import Principal
from app.db.base import utcnow
from app.domain.enums import ApplicationStage, WorkflowStatus
from app.models.governance import WorkflowRun
from app.models.org import Organization
from app.models.pipeline import Application

logger = get_logger(__name__)


@dataclass(frozen=True)
class Node:
    name: str
    kind: str  # auto | human | external | terminal
    waiting_on: str | None = None  # permission (human) or party (external)
    description: str = ""


NODES: dict[str, Node] = {
    n.name: n
    for n in [
        Node("intake", "auto", description="Application received; acknowledgement queued"),
        Node("screening", "auto", description="Screening Agent runs rule checks and evidence summary"),
        Node("screening_review", "human", "screening:review", "Recruiter reviews AI screening and decides"),
        Node(
            "manual_screening",
            "human",
            "screening:review",
            "AI screening unavailable (policy/consent); screen manually",
        ),
        Node("assessment", "external", "candidate", "Candidate completes the assessment"),
        Node("assessment_review", "human", "assessments:score", "Recruiter confirms free-text scoring"),
        Node("interview", "human", "interviews:schedule", "Schedule and conduct interviews; collect scorecards"),
        Node("evaluation", "auto", description="Evaluation Agent consolidates all evidence"),
        Node("evaluation_decision", "human", "evaluations:decide", "Hiring manager decides on selection"),
        Node("selection_approval", "human", "selection:approve", "Selection approval"),
        Node("verification", "human", "verification:manage", "Reference and background checks"),
        Node("offer", "human", "offers:create", "Offer Agent drafts an offer for recruiter review"),
        Node("offer_approval", "human", "offers:approve", "Compensation / offer approval chain"),
        Node("offer_send", "human", "offers:send", "Recruiter sends the approved offer"),
        Node("candidate_response", "external", "candidate", "Candidate accepts or declines"),
        Node("onboarding_handoff", "human", "onboarding:handoff", "Hand over to HRIS / onboarding"),
        Node("done", "terminal", description="Hired and handed off"),
        Node("closed", "terminal", description="Rejected, withdrawn or declined"),
    ]
}

# (current node, event) -> next node
TRANSITIONS: dict[tuple[str, str], str] = {
    ("intake", "application.created"): "screening",
    ("screening", "screening.completed"): "screening_review",
    ("screening", "screening.unavailable"): "manual_screening",
    ("screening_review", "screening.reviewed"): "@next",  # assessment | interview from payload
    ("manual_screening", "screening.reviewed"): "@next",
    ("manual_screening", "screening.completed"): "screening_review",
    ("assessment", "assessment.scored"): "interview",
    ("assessment", "assessment.needs_review"): "assessment_review",
    ("assessment_review", "assessment.scored"): "interview",
    ("interview", "interviews.feedback_complete"): "evaluation",
    ("evaluation", "evaluation.completed"): "evaluation_decision",
    ("evaluation_decision", "evaluation.more_interviews"): "interview",
    ("evaluation_decision", "evaluation.advanced"): "selection_approval",
    ("selection_approval", "selection.approved_verify"): "verification",
    ("selection_approval", "selection.approved_offer"): "offer",
    ("verification", "verification.completed"): "offer",
    ("offer", "offer.submitted"): "offer_approval",
    ("offer_approval", "offer.approved"): "offer_send",
    ("offer_approval", "offer.rejected"): "offer",
    ("offer_send", "offer.sent"): "candidate_response",
    ("candidate_response", "offer.accepted"): "onboarding_handoff",
    ("candidate_response", "offer.declined"): "closed",
    ("onboarding_handoff", "onboarding.handed_off"): "done",
}
STAGE_TO_NODE = {
    ApplicationStage.ASSESSMENT: "assessment",
    ApplicationStage.INTERVIEW: "interview",
}


class Orchestrator:
    def __init__(self, db: Session) -> None:
        self.db = db
        self._auto: dict[str, Callable[[Application, WorkflowRun, Principal | None], str | None]] = {
            "screening": self._run_screening,
            "evaluation": self._run_evaluation,
        }

    # -- persistence --------------------------------------------------------------------
    def get_run(self, app: Application) -> WorkflowRun | None:
        return self.db.scalar(
            select(WorkflowRun).where(WorkflowRun.application_id == app.id, WorkflowRun.workflow == "recruitment")
        )

    def start(self, app: Application, principal: Principal | None = None) -> WorkflowRun:
        run = self.get_run(app)
        if run:
            return run
        run = WorkflowRun(
            organization_id=app.organization_id,
            application_id=app.id,
            current_node="intake",
            status=WorkflowStatus.RUNNING,
            state={"job_id": str(app.job_id)},
            history=[],
        )
        self.db.add(run)
        self.db.flush()
        self.handle(app, "application.created", principal=principal)
        return run

    def _checkpoint(
        self, run: WorkflowRun, node: str, event: str, principal: Principal | None, note: str | None = None
    ) -> None:
        spec = NODES[node]
        run.history = [
            *run.history,
            {
                "from": run.current_node,
                "to": node,
                "event": event,
                "at": utcnow().isoformat(),
                "actor": str(principal.user_id) if principal else "system",
                "note": note,
            },
        ]
        run.current_node = node
        if spec.kind == "terminal":
            run.status, run.waiting_on = (
                (WorkflowStatus.COMPLETED if node == "done" else WorkflowStatus.CANCELLED),
                None,
            )
        elif spec.kind in ("human", "external"):
            run.status, run.waiting_on = WorkflowStatus.WAITING_HUMAN, spec.waiting_on
        else:
            run.status, run.waiting_on = WorkflowStatus.RUNNING, None
        self.db.flush()

    # -- event handling ---------------------------------------------------------------------
    def handle(
        self, app: Application, event: str, *, principal: Principal | None = None, payload: dict[str, Any] | None = None
    ) -> WorkflowRun | None:
        run = self.get_run(app)
        if run is None:
            if event != "application.created":
                return None
            return self.start(app, principal)
        if event == "application.closed":
            if NODES[run.current_node].kind != "terminal":
                self._checkpoint(run, "closed", event, principal)
            return run
        target = TRANSITIONS.get((run.current_node, event))
        if target is None:
            # Out-of-band human action (e.g. recruiter moved stage manually): re-sync with the pipeline.
            synced = STAGE_TO_NODE.get(ApplicationStage(app.stage))
            if synced and synced != run.current_node and event.startswith(("screening.", "stage.")):
                self._checkpoint(run, synced, event, principal, note="resynced from pipeline stage")
            else:
                log_event(logger, "workflow_event_ignored", logging.DEBUG, node=run.current_node, wf_event=event)
            return run
        if target == "@next":
            target = STAGE_TO_NODE.get(ApplicationStage((payload or {}).get("next", app.stage)), "interview")
        self._checkpoint(run, target, event, principal)
        self._drive(app, run, principal)
        return run

    def _drive(self, app: Application, run: WorkflowRun, principal: Principal | None) -> None:
        """Run consecutive automated nodes until the graph interrupts or terminates."""
        for _ in range(10):
            handler = self._auto.get(run.current_node)
            if not handler:
                return
            try:
                next_event = handler(app, run, principal)
            except AppError as exc:
                run.error = exc.detail
                next_event = "screening.unavailable" if run.current_node == "screening" else None
                if not next_event:
                    run.status, run.waiting_on = WorkflowStatus.WAITING_HUMAN, "agents:run"
                    self.db.flush()
                    return
            if not next_event:
                return
            target = TRANSITIONS[(run.current_node, next_event)]
            self._checkpoint(run, target, next_event, principal, note=run.error)
            run.error = None

    # -- automated nodes -------------------------------------------------------------------
    def _run_screening(self, app: Application, run: WorkflowRun, principal: Principal | None) -> str | None:
        from app.services import screening

        org = self.db.get(Organization, app.organization_id)
        policy = (org.settings if org else {}) or {}
        if not policy.get("auto_screen_on_apply", True) and principal is None:
            return "screening.unavailable"
        screening.run(self.db, app, triggered_by=principal, workflow_run_id=run.id)
        return "screening.completed"

    def _run_evaluation(self, app: Application, run: WorkflowRun, principal: Principal | None) -> str | None:
        from app.services import selection

        selection.run_evaluation(self.db, app, principal, workflow_run_id=run.id)
        return "evaluation.completed"


def describe_graph() -> dict[str, Any]:
    return {
        "nodes": [
            {"name": n.name, "kind": n.kind, "waiting_on": n.waiting_on, "description": n.description}
            for n in NODES.values()
        ],
        "edges": [{"from": a, "event": e, "to": b} for (a, e), b in TRANSITIONS.items()],
    }
