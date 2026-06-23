"""Configurable release-state machine.

The state graph is data-driven: it is loaded from the database (seeded by the
workflow migration, editable at runtime). Each state has an ordinal *score*
(its position), zero or more named transitions, and is *final* when it has no
transitions. This lets the workflow change without code edits. The graph can be
exported back to states.yaml-compatible YAML via :func:`dump_yaml`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import yaml


@dataclass(frozen=True)
class Transition:
    name: str
    target: str
    # Roles permitted to perform this transition. Empty means "fall back to the
    # state machine's default roles" (resolved by callers, not stored here).
    roles: frozenset[str] = frozenset()
    # Readiness requirements (guards) that must be satisfied before this
    # transition is allowed, e.g. "no_open_issues", "docs_complete". Empty means
    # the transition is unguarded. The state machine carries these declaratively;
    # the release API evaluates them against the release's current status.
    requires: frozenset[str] = frozenset()


@dataclass
class State:
    name: str
    score: int
    transitions: dict[str, Transition] = field(default_factory=dict)

    @property
    def is_final(self) -> bool:
        return not self.transitions


# Readiness guards a transition may declare in `requires`. Mirrors the checks
# evaluated by the release API (see release._unmet_requirements).
KNOWN_GUARDS = frozenset({"no_open_issues", "docs_complete", "checks_done"})

# Parameterised guard: ``document:<TypeName>`` requires that at least one document
# of that type has been uploaded to the release before the transition is allowed.
# The <TypeName> is one of the admin-configured document types.
DOCUMENT_GUARD_PREFIX = "document:"


def is_document_guard(guard: str) -> bool:
    return guard.startswith(DOCUMENT_GUARD_PREFIX)


def document_guard_type(guard: str) -> str:
    """The document type named by a ``document:<TypeName>`` guard."""
    return guard[len(DOCUMENT_GUARD_PREFIX):]


# Prepended to exported YAML so a downloaded states.yaml keeps its bearings.
_YAML_HEADER = (
    "# Release state graph (acyclic). Position defines the score / ordering.\n"
    "# A state with no transitions is final.\n"
    "#\n"
    "# Exported from the database-backed workflow. Each transition may declare\n"
    "# `roles` (who may perform it) and `requires` (readiness guards:\n"
    "# no_open_issues, docs_complete, checks_done, or document:<TypeName> to\n"
    "# require an uploaded document of that type).\n"
)


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

    def states(self) -> list[State]:
        """All states ordered by score (workflow ordering)."""
        return sorted(self._states.values(), key=lambda s: s.score)

    def transition(self, state: str, transition_name: str) -> Transition | None:
        """Return the named transition object out of ``state`` (or None)."""
        self._require(state)
        return self._states[state].transitions.get(transition_name)

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


def build_state_machine(rows: list[dict]) -> StateMachine:
    """Construct a StateMachine from an ordered list of state rows (from the
    database or parsed YAML). Each row is
    ``{name, transitions: [{name, target, roles, requires}]}``; the list order
    defines each state's score, so the first row is the initial state."""
    states: list[State] = []
    for score, entry in enumerate(rows):
        transitions = {
            t["name"]: Transition(
                name=t["name"],
                target=t["target"],
                roles=frozenset(t.get("roles") or ()),
                requires=frozenset(t.get("requires") or ()),
            )
            for t in (entry.get("transitions") or [])
        }
        states.append(State(name=entry["name"], score=score, transitions=transitions))
    return StateMachine(states)


def dump_yaml(sm: StateMachine) -> str:
    """Serialise a state machine into states.yaml-compatible YAML.

    ``target`` becomes ``state`` and empty ``roles``/``requires`` are omitted so
    the output mirrors a hand-authored states.yaml that leaves them to fall back
    on the defaults."""
    states_out: list[dict] = []
    for state in sm.states():
        entry: dict = {"name": state.name}
        transitions = []
        for t in state.transitions.values():
            td: dict = {"name": t.name, "state": t.target}
            if t.roles:
                td["roles"] = sorted(t.roles)
            if t.requires:
                td["requires"] = sorted(t.requires)
            transitions.append(td)
        if transitions:
            entry["transitions"] = transitions
        states_out.append(entry)
    body = yaml.safe_dump({"State": states_out}, sort_keys=False, default_flow_style=False)
    return _YAML_HEADER + body
