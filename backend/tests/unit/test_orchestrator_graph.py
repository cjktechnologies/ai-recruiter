from __future__ import annotations

from app.ai.orchestrator import NODES, TRANSITIONS, describe_graph


def test_graph_is_well_formed() -> None:
    for (src, event), dst in TRANSITIONS.items():
        assert src in NODES, src
        assert dst == "@next" or dst in NODES, dst
        assert "." in event
    for n in NODES.values():
        if n.kind == "human":
            assert n.waiting_on and ":" in n.waiting_on, n.name
    # Every non-terminal node has an outgoing edge.
    sources = {s for s, _ in TRANSITIONS}
    for name, n in NODES.items():
        if n.kind != "terminal":
            assert name in sources, name


def test_consequential_nodes_are_human_interrupts() -> None:
    for name in (
        "screening_review",
        "evaluation_decision",
        "selection_approval",
        "offer_approval",
        "offer_send",
        "onboarding_handoff",
    ):
        assert NODES[name].kind == "human"
    assert {n["name"] for n in describe_graph()["nodes"]} == set(NODES)
