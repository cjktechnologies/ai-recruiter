from __future__ import annotations

import itertools

import pytest

from app.domain.enums import ApplicationStage as S
from app.domain.permissions import ALL_PERMISSIONS, MODULE_ACTIONS, ROLE_PERMISSIONS, Role, permissions_for
from app.domain.pipeline import HUMAN_GATES, TERMINAL, can_transition, gate_for


def test_every_module_has_permissions_and_roles_use_known_permissions() -> None:
    assert len(ALL_PERMISSIONS) == sum(len(v) for v in MODULE_ACTIONS.values())
    for role, perms in ROLE_PERMISSIONS.items():
        assert perms <= ALL_PERMISSIONS, role


@pytest.mark.parametrize(
    ("role", "allowed", "denied"),
    [
        (
            Role.RECRUITER,
            {"screening:review", "offers:send", "candidates:read_pii"},
            {"offers:approve", "selection:approve", "governance:manage", "users:create"},
        ),
        (
            Role.HIRING_MANAGER,
            {"evaluations:decide", "requisitions:approve", "selection:approve"},
            {"offers:approve", "candidates:read_pii", "compensation:manage", "audit:read"},
        ),
        (
            Role.INTERVIEWER,
            {"interviews:feedback", "candidates:read"},
            {"screening:review", "offers:read", "analytics:read", "candidates:read_pii"},
        ),
        (
            Role.FINANCE_APPROVER,
            {"offers:approve", "compensation:approve"},
            {"candidates:read", "screening:review", "interviews:feedback"},
        ),
        (Role.CANDIDATE, set(), {"candidates:read", "applications:read"}),
    ],
)
def test_role_permission_matrix(role: Role, allowed: set[str], denied: set[str]) -> None:
    perms = ROLE_PERMISSIONS[role]
    assert allowed <= perms
    assert not (denied & perms)


def test_permissions_union_and_custom_roles() -> None:
    perms = permissions_for(["interviewer", "finance_approver"])
    assert {"interviews:feedback", "offers:approve"} <= perms
    assert permissions_for(["custom"], {"custom": frozenset({"jobs:read"})}) == {"jobs:read"}
    assert permissions_for(["nonexistent"]) == set()


def test_pipeline_happy_path_transitions() -> None:
    path = [
        S.APPLIED,
        S.SCREENING,
        S.SCREENED,
        S.ASSESSMENT,
        S.INTERVIEW,
        S.EVALUATION,
        S.SELECTION,
        S.VERIFICATION,
        S.OFFER,
        S.HIRED,
    ]
    for a, b in itertools.pairwise(path):
        assert can_transition(a, b), (a, b)


def test_pipeline_rejects_skips_and_terminal_changes() -> None:
    assert not can_transition(S.APPLIED, S.OFFER)
    assert not can_transition(S.SCREENED, S.HIRED)
    for t in TERMINAL:
        assert not can_transition(t, S.SCREENING)
    assert can_transition(S.INTERVIEW, S.REJECTED)
    assert can_transition(S.OFFER, S.WITHDRAWN)


def test_consequential_transitions_are_human_gated() -> None:
    assert gate_for(S.SCREENED, S.INTERVIEW).permission == "screening:review"  # type: ignore[union-attr]
    assert gate_for(S.EVALUATION, S.SELECTION).permission == "evaluations:decide"  # type: ignore[union-attr]
    assert gate_for(S.SELECTION, S.OFFER).permission == "selection:approve"  # type: ignore[union-attr]
    assert gate_for(S.INTERVIEW, S.REJECTED).permission == "applications:reject"  # type: ignore[union-attr]
    assert gate_for(S.APPLIED, S.SCREENING) is None  # automation allowed
    assert (S.OFFER, S.HIRED) in HUMAN_GATES
