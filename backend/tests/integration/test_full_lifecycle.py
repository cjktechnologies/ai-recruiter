"""End-to-end recruitment lifecycle through the public API:

requisition → approval → JD → job → publish → public application (CV) → AI screening → human review →
assessment → interviews → scorecards → evaluation → selection approval → verification → offer →
approval chain → send → acceptance → onboarding handoff.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import session_scope
from app.integrations.messaging import ConsoleEmailSender
from app.models.governance import AuditLog, WorkflowRun
from tests.factories import API, SENIOR_CV, Tenant, requisition_payload

pytestmark = pytest.mark.integration


def _ok(r, code: int = 200):  # type: ignore[no-untyped-def]
    assert r.status_code == code, f"{r.status_code}: {r.text}"
    return r.json()


def create_published_job(client: TestClient, t: Tenant) -> dict:
    req = _ok(
        client.post(
            f"{API}/requisitions",
            json=requisition_payload(
                hiring_manager_id=str(t.users["hiring_manager"]), recruiter_id=str(t.users["recruiter"])
            ),
            headers=t.h("recruiter"),
        ),
        201,
    )
    sub = _ok(client.post(f"{API}/requisitions/{req['id']}/submit", headers=t.h("recruiter")))
    assert sub["status"] == "pending_approval"
    assert sub["ai_validation"]["valid"] is True
    route = [s["approver_role"] for s in sub["approval"]["steps"]]
    assert route == ["hiring_manager", "hr_manager"]
    # A recruiter cannot approve.
    assert (
        client.post(
            f"{API}/requisitions/{req['id']}/decision", json={"decision": "approve"}, headers=t.h("recruiter")
        ).status_code
        == 403
    )
    # Out-of-order approver (HR before hiring manager) is refused.
    assert (
        client.post(
            f"{API}/requisitions/{req['id']}/decision", json={"decision": "approve"}, headers=t.h("hr_manager")
        ).status_code
        == 403
    )
    _ok(
        client.post(
            f"{API}/requisitions/{req['id']}/decision",
            json={"decision": "approve", "comment": "ok"},
            headers={**t.h("hiring_manager"), "Idempotency-Key": "approve-req-1"},
        )
    )
    # Idempotent replay returns the same result instead of acting twice.
    _ok(
        client.post(
            f"{API}/requisitions/{req['id']}/decision",
            json={"decision": "approve", "comment": "ok"},
            headers={**t.h("hiring_manager"), "Idempotency-Key": "approve-req-1"},
        )
    )
    done = _ok(
        client.post(f"{API}/requisitions/{req['id']}/decision", json={"decision": "approve"}, headers=t.h("hr_manager"))
    )
    assert done["status"] == "approved"

    job = _ok(client.post(f"{API}/requisitions/{req['id']}/jobs", headers=t.h("recruiter")), 201)
    assert "Senior Backend Engineer" in job["description"]
    assert {r["name"] for r in job["requirements"]} >= {"Python", "PostgreSQL", "AWS"}
    job = _ok(
        client.patch(
            f"{API}/jobs/{job['id']}",
            json={
                "screening_config": {
                    "knockout_questions": [
                        {"id": "work_permit", "question": "Do you have the right to work in SA?", "expected": True}
                    ]
                }
            },
            headers=t.h("recruiter"),
        )
    )
    job = _ok(client.post(f"{API}/jobs/{job['id']}/publish", headers=t.h("recruiter")))
    assert job["status"] == "published"
    return job


def apply_publicly(
    client: TestClient,
    t: Tenant,
    job: dict,
    email: str,
    cv: str,
    answers: dict | None = None,
    first: str = "Jane",
    last: str = "Doe",
) -> None:
    r = client.post(
        f"{API}/public/{t.slug}/jobs/{job['slug']}/apply",
        data={
            "first_name": first,
            "last_name": last,
            "email": email,
            "consent_recruitment": "true",
            "answers": json.dumps(answers or {"work_permit": True}),
            "eeo": json.dumps({"gender": "female"}),
        },
        files={"cv": ("cv.txt", cv.encode(), "text/plain")},
        headers={"Idempotency-Key": f"apply-{email}"},
    )
    _ok(r, 201)


def test_full_recruitment_lifecycle(client: TestClient, tenant: Tenant) -> None:
    t = tenant
    job = create_published_job(client, t)

    # Careers site lists the job, without exposing internal screening config.
    public = _ok(client.get(f"{API}/public/{t.slug}/jobs"))
    assert public[0]["slug"] == job["slug"] and "screening_config" not in public[0]

    apply_publicly(client, t, job, "jane.doe@example.com", SENIOR_CV)
    # Retry with the same idempotency key does not create a duplicate application.
    apply_publicly(client, t, job, "jane.doe@example.com", SENIOR_CV)
    apps = _ok(client.get(f"{API}/applications", params={"job_id": job["id"]}, headers=t.h("recruiter")))
    assert apps["total"] == 1
    app = apps["items"][0]
    assert app["stage"] == "screened", "AI screening runs automatically but stops at the human gate"
    assert any("received your application" in m["subject"] for m in ConsoleEmailSender.outbox)

    detail = _ok(client.get(f"{API}/applications/{app['id']}", headers=t.h("recruiter")))
    assert detail["workflow"]["current_node"] == "screening_review"
    assert detail["workflow"]["waiting_on"] == "screening:review"

    # CV parsing enriched the profile with evidence-backed skills.
    cand = _ok(client.get(f"{API}/candidates/{app['candidate_id']}", headers=t.h("recruiter")))
    skills = {s["name"]: s for s in cand["skills"]}
    assert {"Python", "PostgreSQL", "AWS", "Kafka"} <= set(skills)
    assert skills["Python"]["evidence"]

    screening = _ok(client.get(f"{API}/applications/{app['id']}/screening", headers=t.h("recruiter")))[0]
    assert screening["eligible"] is True
    assert screening["recommendation"] in ("yes", "strong_yes")
    assert all(f["evidence"] for f in screening["facts"] if f["source"] == "candidate_material")
    assert screening["review_status"] == "pending_review"

    # Agents may not cross the human gate; neither can an interviewer.
    assert (
        client.post(
            f"{API}/applications/{app['id']}/move", json={"to_stage": "assessment"}, headers=t.h("interviewer")
        ).status_code
        == 403
    )
    queue = _ok(client.get(f"{API}/screening/queue", headers=t.h("recruiter")))
    assert queue[0]["screening"]["id"] == screening["id"]

    _ok(
        client.post(
            f"{API}/screening/{screening['id']}/review",
            json={"decision": "advance", "next_stage": "assessment"},
            headers=t.h("recruiter"),
        )
    )

    # --- Assessment ---------------------------------------------------------------------
    q1 = _ok(
        client.post(
            f"{API}/question-bank",
            json={
                "kind": "single_choice",
                "prompt": "Which isolation level prevents phantom reads in PostgreSQL?",
                "options": ["READ COMMITTED", "SERIALIZABLE"],
                "correct_answer": {"value": "SERIALIZABLE"},
                "competency": "PostgreSQL",
                "points": 2,
                "tags": ["postgresql"],
            },
            headers=t.h("recruiter"),
        ),
        201,
    )
    q2 = _ok(
        client.post(
            f"{API}/question-bank",
            json={
                "kind": "long_text",
                "prompt": "Explain how you would make a Python service idempotent.",
                "correct_answer": {"keywords": ["idempotency key", "retry", "unique"]},
                "competency": "Python",
                "points": 3,
                "tags": ["python"],
            },
            headers=t.h("recruiter"),
        ),
        201,
    )
    assessment = _ok(
        client.post(f"{API}/assessments/generate", json={"job_id": job["id"]}, headers=t.h("recruiter")), 201
    )
    assert {q["prompt"] for q in assessment["questions"]} == {q1["prompt"], q2["prompt"]}
    invite = _ok(
        client.post(
            f"{API}/applications/{app['id']}/assessments",
            json={"assessment_id": assessment["id"]},
            headers=t.h("recruiter"),
        ),
        201,
    )
    token = invite["candidate_link"].rsplit("/", 1)[1]
    public_a = _ok(client.get(f"{API}/public/assessments/{token}"))
    assert all("correct_answer" not in q for q in public_a["questions"]), "answer key must never leak"
    ids = {q["prompt"]: q["id"] for q in public_a["questions"]}
    _ok(
        client.post(
            f"{API}/public/assessments/{token}/submit",
            json={
                "answers": {
                    ids[q1["prompt"]]: "SERIALIZABLE",
                    ids[q2["prompt"]]: "Use an idempotency key stored with a unique constraint so a retry is harmless.",
                }
            },
        )
    )
    results = _ok(client.get(f"{API}/applications/{app['id']}/assessment-results", headers=t.h("recruiter")))
    assert results[0]["status"] == "submitted", "free text requires human confirmation"
    _ok(
        client.post(
            f"{API}/assessment-results/{results[0]['id']}/score",
            json={"question_scores": {ids[q2["prompt"]]: 3}},
            headers=t.h("recruiter"),
        )
    )
    scored = _ok(client.get(f"{API}/applications/{app['id']}/assessment-results", headers=t.h("recruiter")))[0]
    assert scored["percentage"] == 100.0 and scored["passed"] is True
    assert _ok(client.get(f"{API}/applications/{app['id']}", headers=t.h("recruiter")))["stage"] == "interview"

    # --- Interviews -------------------------------------------------------------------------
    template = _ok(
        client.post(
            f"{API}/interview-templates",
            json={
                "name": "Backend technical",
                "kind": "technical",
                "competencies": [
                    {"name": "System design", "keywords": ["design", "architecture", "scale"]},
                    {"name": "Collaboration", "keywords": ["team", "mentor"]},
                ],
            },
            headers=t.h("recruiter"),
        ),
        201,
    )
    slots = _ok(
        client.post(
            f"{API}/applications/{app['id']}/interview-slots",
            json={"interviewer_ids": [str(t.users["interviewer"]), str(t.users["interviewer2"])]},
            headers=t.h("recruiter"),
        )
    )
    assert slots, "scheduling agent proposes slots"
    start = datetime.now(UTC) + timedelta(minutes=2)
    iv = _ok(
        client.post(
            f"{API}/applications/{app['id']}/interviews",
            json={
                "kind": "technical",
                "template_id": template["id"],
                "scheduled_start": start.isoformat(),
                "scheduled_end": (start + timedelta(hours=1)).isoformat(),
                "interviewer_ids": [str(t.users["interviewer"]), str(t.users["interviewer2"])],
            },
            headers=t.h("recruiter"),
        ),
        201,
    )
    assert iv["calendar_event_id"]
    # Double-booking the same panel is refused.
    assert (
        client.post(
            f"{API}/applications/{app['id']}/interviews",
            json={
                "kind": "technical",
                "scheduled_start": start.isoformat(),
                "scheduled_end": (start + timedelta(hours=1)).isoformat(),
                "interviewer_ids": [str(t.users["interviewer"])],
            },
            headers=t.h("recruiter"),
        ).status_code
        == 409
    )

    iv = _ok(
        client.post(
            f"{API}/interviews/{iv['id']}/transcript",
            json={
                "consent_confirmed": True,
                "transcript": "Interviewer: Tell me about a system you designed.\nCandidate: I designed the settlement "
                "architecture to scale to ten million events per day using Kafka partitions.\n"
                "Candidate: I also mentor two engineers in my team and run design reviews.",
            },
            headers=t.h("interviewer"),
        )
    )
    evidence = {e["competency"]: e for e in iv["ai_summary"]["competency_evidence"]}
    assert evidence["System design"]["quotes"] and evidence["Collaboration"]["quotes"]

    # Scorecards can't be submitted before the interview starts; move the interview into the past.
    from app.models.interviews import Interview

    with session_scope() as db:
        row = db.get(Interview, uuid.UUID(iv["id"]))
        assert row
        row.scheduled_start = datetime.now(UTC) - timedelta(hours=2)
        row.scheduled_end = datetime.now(UTC) - timedelta(hours=1)
    # Only assigned interviewers can submit.
    assert (
        client.post(
            f"{API}/interviews/{iv['id']}/scorecards",
            json={"overall_rating": 4, "recommendation": "yes"},
            headers=t.h("hiring_manager"),
        ).status_code
        == 403
    )
    for who, rating in (("interviewer", 5), ("interviewer2", 4)):
        _ok(
            client.post(
                f"{API}/interviews/{iv['id']}/scorecards",
                json={
                    "overall_rating": rating,
                    "recommendation": "strong_yes" if rating == 5 else "yes",
                    "ratings": [
                        {"competency": "System design", "rating": rating, "evidence": "Kafka design"},
                        {"competency": "Collaboration", "rating": 4, "evidence": "mentoring"},
                    ],
                },
                headers=t.h(who),
            ),
            201,
        )
    # Panelists see only their own card (independent feedback).
    assert len(_ok(client.get(f"{API}/interviews/{iv['id']}/scorecards", headers=t.h("interviewer")))) == 1

    # All feedback in → Evaluation Agent ran automatically.
    detail = _ok(client.get(f"{API}/applications/{app['id']}", headers=t.h("hiring_manager")))
    assert detail["stage"] == "evaluation"
    assert detail["workflow"]["current_node"] == "evaluation_decision"
    ev = _ok(client.get(f"{API}/applications/{app['id']}/evaluations", headers=t.h("hiring_manager")))[0]
    assert ev["ai_recommendation"] in ("yes", "strong_yes") and ev["decision"] is None
    assert ev["competency_matrix"]["System design"]["mean"] == 4.5

    _ok(
        client.post(
            f"{API}/evaluations/{ev['id']}/decision",
            json={"decision": "advance_to_selection", "rationale": "Strong system design and collaboration evidence."},
            headers=t.h("hiring_manager"),
        )
    )

    # --- Selection approval (segregation of duties) -------------------------------------------
    assert (
        client.post(
            f"{API}/applications/{app['id']}/selection", json={"decision": "approve"}, headers=t.h("hiring_manager")
        ).status_code
        == 422
    )
    _ok(
        client.post(
            f"{API}/applications/{app['id']}/selection",
            json={"decision": "approve", "comment": "Go"},
            headers=t.h("hr_manager"),
        )
    )

    # --- Verification ---------------------------------------------------------------------------
    ref = _ok(
        client.post(
            f"{API}/applications/{app['id']}/references",
            json={
                "referee_name": "Pat Referee",
                "referee_email": "pat@beta.example",
                "relationship_to_candidate": "Manager",
            },
            headers=t.h("recruiter"),
        ),
        201,
    )
    ref_token = ref["referee_link"].rsplit("/", 1)[1]
    assert _ok(client.get(f"{API}/public/references/{ref_token}"))["questions"]
    bc = _ok(
        client.post(
            f"{API}/applications/{app['id']}/background-checks",
            json={"consent_confirmed": True},
            headers=t.h("recruiter"),
        ),
        201,
    )
    _ok(
        client.post(
            f"{API}/public/references/{ref_token}",
            json={"responses": {"strengths": "Excellent engineer", "rehire": "yes"}},
        )
    )
    assert client.post(f"{API}/public/references/{ref_token}", json={"responses": {}}).status_code == 404
    _ok(
        client.patch(
            f"{API}/background-checks/{bc['id']}",
            json={"status": "completed", "result": "clear"},
            headers=t.h("recruiter"),
        )
    )
    assert _ok(client.get(f"{API}/applications/{app['id']}", headers=t.h("recruiter")))["stage"] == "offer"

    # --- Offer -------------------------------------------------------------------------------------
    offer = _ok(client.post(f"{API}/applications/{app['id']}/offers", json={}, headers=t.h("recruiter")), 201)
    assert offer["within_band"] is True and 100000 <= float(offer["base_salary"]) <= 135000
    assert [a["approver_role"] for a in offer["approvals"]] == ["hr_manager", "hiring_manager"]
    # Push salary out of band → finance approval is required automatically.
    offer = _ok(client.patch(f"{API}/offers/{offer['id']}", json={"base_salary": "150000"}, headers=t.h("recruiter")))
    assert offer["within_band"] is False
    assert "finance_approver" in [a["approver_role"] for a in offer["approvals"]]
    offer = _ok(client.patch(f"{API}/offers/{offer['id']}", json={"base_salary": "130000"}, headers=t.h("recruiter")))
    _ok(client.post(f"{API}/offers/{offer['id']}/submit", headers=t.h("recruiter")))
    assert client.post(f"{API}/offers/{offer['id']}/send", headers=t.h("recruiter")).status_code == 409
    for role in ("hr_manager", "hiring_manager", "finance_approver"):
        r = client.post(f"{API}/offers/{offer['id']}/decision", json={"decision": "approve"}, headers=t.h(role))
        if role == "hiring_manager":
            assert r.status_code == 403, "hiring managers lack offers:approve"
            r = client.post(
                f"{API}/offers/{offer['id']}/decision", json={"decision": "approve"}, headers=t.h("org_admin")
            )
        _ok(r)
        if _ok(client.get(f"{API}/offers/{offer['id']}", headers=t.h("recruiter")))["status"] == "approved":
            break
    sent = _ok(
        client.post(f"{API}/offers/{offer['id']}/send", headers={**t.h("recruiter"), "Idempotency-Key": "send-offer-1"})
    )
    resent = _ok(
        client.post(f"{API}/offers/{offer['id']}/send", headers={**t.h("recruiter"), "Idempotency-Key": "send-offer-1"})
    )
    assert sent["candidate_link"] == resent["candidate_link"]
    offer_token = sent["candidate_link"].rsplit("/", 1)[1]
    assert _ok(client.get(f"{API}/public/offers/{offer_token}"))["job_title"] == "Senior Backend Engineer"
    _ok(client.post(f"{API}/public/offers/{offer_token}/respond", json={"accept": True}))
    assert _ok(client.get(f"{API}/applications/{app['id']}", headers=t.h("recruiter")))["stage"] == "hired"

    # --- Onboarding --------------------------------------------------------------------------------
    h = _ok(
        client.post(
            f"{API}/applications/{app['id']}/onboarding", headers={**t.h("recruiter"), "Idempotency-Key": "handoff-1"}
        )
    )
    assert h["status"] == "done" and h["payload"]["job"]["title"] == "Senior Backend Engineer"
    ob = _ok(client.get(f"{API}/applications/{app['id']}/onboarding", headers=t.h("recruiter")))
    assert {t_["category"] for t_ in ob["tasks"]} >= {"it", "hr", "preboarding", "payroll"}
    wf = _ok(client.get(f"{API}/applications/{app['id']}/workflow", headers=t.h("recruiter")))
    assert wf["status"] == "completed" and wf["current_node"] == "done"

    req = _ok(client.get(f"{API}/requisitions", headers=t.h("recruiter")))["items"][0]
    assert req["status"] == "filled"

    # --- Governance evidence -------------------------------------------------------------------------
    with session_scope() as db:
        actions = {a.action for a in db.scalars(select(AuditLog).where(AuditLog.organization_id == t.org_id))}
        run = db.scalar(select(WorkflowRun))
        assert run and len(run.history) >= 10
    for expected in (
        "requisition.submitted",
        "screening.reviewed",
        "evaluation.decided",
        "selection.decision",
        "offer.sent",
        "offer.accepted",
        "onboarding.handoff",
        "application.hired",
    ):
        assert expected in actions, expected
    execs = _ok(client.get(f"{API}/agents/executions", params={"page_size": 100}, headers=t.h("org_admin")))
    agents_used = {e["agent"] for e in execs["items"]}
    assert {
        "requisition",
        "job_description",
        "screening",
        "assessment",
        "scheduling",
        "interview_assistant",
        "evaluation",
        "offer",
        "onboarding",
    } <= agents_used
    metrics = _ok(client.get(f"{API}/analytics/overview", headers=t.h("hr_manager")))
    assert metrics["hires"] == 1 and metrics["offer_acceptance_rate"] == 100.0
    assert metrics["funnel"]["applied"] == 1 and metrics["time_to_hire_days"] is not None
    insights = _ok(client.get(f"{API}/analytics/insights", headers=t.h("hr_manager")))
    assert "insights" in insights


def test_rejected_candidate_is_notified_and_workflow_closed(client: TestClient, tenant: Tenant) -> None:
    t = tenant
    job = create_published_job(client, t)
    apply_publicly(
        client,
        t,
        job,
        "john@example.com",
        "John Smith\nJunior Web Developer\nHTML, CSS",
        answers={"work_permit": False},
        first="John",
        last="Smith",
    )
    app = _ok(client.get(f"{API}/applications", headers=t.h("recruiter")))["items"][0]
    scr = _ok(client.get(f"{API}/applications/{app['id']}/screening", headers=t.h("recruiter")))[0]
    assert scr["eligible"] is False and scr["recommendation"] in ("no", "strong_no")
    # Advancing against the AI recommendation requires a documented reason.
    r = client.post(f"{API}/screening/{scr['id']}/review", json={"decision": "advance"}, headers=t.h("recruiter"))
    assert r.status_code == 422
    _ok(
        client.post(
            f"{API}/screening/{scr['id']}/review",
            json={"decision": "reject", "rejection_reason": "Missing core skills"},
            headers=t.h("recruiter"),
        )
    )
    detail = _ok(client.get(f"{API}/applications/{app['id']}", headers=t.h("recruiter")))
    assert detail["stage"] == "rejected" and detail["workflow"]["status"] == "cancelled"
    assert any("Your application for" in m["subject"] for m in ConsoleEmailSender.outbox)
