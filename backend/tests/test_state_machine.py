"""Unit tests for the configurable release-state machine (no DB required)."""
from __future__ import annotations

import pytest
import yaml

from app.services.state_machine import build_state_machine, dump_yaml, StateError

# The standard workflow, mirroring the seed in migration 0006 (row shape: the
# same structure repositories.workflow.load returns from the database).
ROWS = [
    {"name": "Draft", "transitions": [
        {"name": "Ready", "target": "In QA",
         "roles": ["Developer", "Release Manager", "Administrator"], "requires": []},
        {"name": "Cancel", "target": "Cancelled",
         "roles": ["Developer", "Release Manager", "Administrator"], "requires": []},
    ]},
    {"name": "In QA", "transitions": [
        {"name": "Approve", "target": "Approved",
         "roles": ["QA Manager", "Release Manager", "Administrator"],
         "requires": ["no_open_issues", "docs_complete"]},
        {"name": "Reject", "target": "Rejected",
         "roles": ["QA Manager", "Release Manager", "Administrator"], "requires": []},
    ]},
    {"name": "Cancelled", "transitions": []},
    {"name": "Rejected", "transitions": []},
    {"name": "Approved", "transitions": []},
]


@pytest.fixture
def sm():
    return build_state_machine(ROWS)


def test_initial_state_is_lowest_score(sm):
    assert sm.initial_state == "Draft"


def test_state_ordering_by_score(sm):
    # List position defines the score: Draft < In QA < Cancelled < Rejected < Approved
    assert sm.score("Draft") < sm.score("In QA") < sm.score("Cancelled")
    assert sm.score("Cancelled") < sm.score("Rejected") < sm.score("Approved")


def test_legal_transition(sm):
    assert sm.apply("Draft", "Ready") == "In QA"
    assert sm.apply("In QA", "Approve") == "Approved"
    assert sm.apply("In QA", "Reject") == "Rejected"


def test_illegal_transition_raises(sm):
    with pytest.raises(StateError):
        sm.apply("Draft", "Approve")


def test_final_states_have_no_transitions(sm):
    for final in ("Approved", "Rejected", "Cancelled"):
        assert sm.transitions(final) == []


def test_unknown_state_raises(sm):
    with pytest.raises(StateError):
        sm.apply("Nope", "Ready")


def _normalise(rows):
    """Sort each transition's roles/requires so comparisons ignore ordering
    (dump_yaml sorts them; the seed lists them in priority order)."""
    return [
        {
            "name": s["name"],
            "transitions": [
                {**t, "roles": sorted(t["roles"]), "requires": sorted(t["requires"])}
                for t in s["transitions"]
            ],
        }
        for s in rows
    ]


def _parse_exported(text: str) -> list[dict]:
    """Read exported states.yaml back into the row shape (state -> target)."""
    raw = yaml.safe_load(text)
    return [
        {
            "name": e["name"],
            "transitions": [
                {"name": t["name"], "target": t["state"],
                 "roles": list(t.get("roles") or []), "requires": list(t.get("requires") or [])}
                for t in (e.get("transitions") or [])
            ],
        }
        for e in raw["State"]
    ]


def test_dump_yaml_round_trips():
    # build -> dump -> parse must preserve names, targets, roles and guards.
    dumped = dump_yaml(build_state_machine(ROWS))
    assert _normalise(_parse_exported(dumped)) == _normalise(ROWS)


def test_dump_yaml_omits_empty_roles_and_requires():
    rows = [
        {"name": "A", "transitions": [{"name": "go", "target": "B", "roles": [], "requires": []}]},
        {"name": "B", "transitions": []},
    ]
    dumped = dump_yaml(build_state_machine(rows))
    # The header references roles/requires; the serialised body must not.
    assert "roles:" not in dumped
    assert "requires:" not in dumped
    assert "state: B" in dumped
