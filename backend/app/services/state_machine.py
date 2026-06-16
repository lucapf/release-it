"""Configurable release-state machine.

The state graph is data-driven: it is loaded from a YAML file (see
``app/config/states.yaml``) at startup. Each state has an ordinal *score*
(its position in the YAML), zero or more named transitions, and is *final*
when it has no transitions. This lets the workflow change without code edits.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Transition:
    name: str
    target: str


@dataclass
class State:
    name: str
    score: int
    transitions: dict[str, Transition] = field(default_factory=dict)

    @property
    def is_final(self) -> bool:
        return not self.transitions


class StateError(ValueError):
    """Raised for unknown states or illegal transitions."""


class StateMachine:
    def __init__(self, states: list[State]):
        self._states: dict[str, State] = {s.name: s for s in states}
        if not self._states:
            raise StateError("State machine has no states configured")

    @property
    def initial_state(self) -> str:
        """The lowest-scored state is the entry point (e.g. 'Draft')."""
        return min(self._states.values(), key=lambda s: s.score).name

    def exists(self, state: str) -> bool:
        return state in self._states

    def score(self, state: str) -> int:
        self._require(state)
        return self._states[state].score

    def transitions(self, state: str) -> list[Transition]:
        self._require(state)
        return list(self._states[state].transitions.values())

    def apply(self, current: str, transition_name: str) -> str:
        """Return the target state for a named transition, or raise StateError."""
        self._require(current)
        trans = self._states[current].transitions.get(transition_name)
        if trans is None:
            allowed = ", ".join(self._states[current].transitions) or "(none — final state)"
            raise StateError(
                f"Transition '{transition_name}' is not allowed from '{current}'. "
                f"Allowed: {allowed}"
            )
        return trans.target

    def _require(self, state: str) -> None:
        if state not in self._states:
            raise StateError(f"Unknown state '{state}'")


def load_state_machine(path: str | Path) -> StateMachine:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    entries = raw.get("State", []) if isinstance(raw, dict) else []
    states: list[State] = []
    for score, entry in enumerate(entries):
        transitions = {
            t["name"]: Transition(name=t["name"], target=t["state"])
            for t in (entry.get("transitions") or [])
        }
        states.append(State(name=entry["name"], score=score, transitions=transitions))
    return StateMachine(states)
