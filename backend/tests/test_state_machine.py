"""Unit tests for the configurable release-state machine (no DB required)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.state_machine import StateError, load_state_machine

STATES = Path(__file__).resolve().parents[1] / "app" / "config" / "states.yaml"


@pytest.fixture
def sm():
    return load_state_machine(STATES)


def test_initial_state_is_lowest_score(sm):
    assert sm.initial_state == "Draft"


def test_state_ordering_by_score(sm):
    # Position in YAML defines the score: Draft < In QA < Cancelled < Rejected < Approved
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
