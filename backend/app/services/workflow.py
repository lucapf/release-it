"""Database-backed release workflow: load, replace and export.

The state graph lives in the ``workflow_state`` / ``workflow_transition`` tables
(see migration 0006, which also seeds the standard workflow), editable at
runtime via the configuration page. This module is the single place that turns
those rows into a :class:`StateMachine` and validates edits.
"""
from __future__ import annotations

import psycopg

from app.core.jwt_verify import ALL_ROLES
from app.repositories import config as config_repo
from app.repositories import workflow as repo
from app.services import appconfig
from app.services.state_machine import (
    KNOWN_GUARDS,
    StateError,
    StateMachine,
    build_state_machine,
    document_guard_type,
    dump_yaml,
    is_document_guard,
)


def from_db(conn: psycopg.Connection) -> StateMachine:
    """Build the StateMachine from the persisted workflow graph."""
    return build_state_machine(repo.load(conn))


def export_yaml(conn: psycopg.Connection) -> str:
    """Serialise the persisted workflow as states.yaml-compatible YAML."""
    return dump_yaml(from_db(conn))


def replace(conn: psycopg.Connection, states: list[dict]) -> StateMachine:
    """Validate and persist a complete new workflow graph, returning the rebuilt
    StateMachine. ``states`` is the ordered list of
    ``{name, transitions: [{name, target, roles, requires}]}``."""
    _validate(states, config_repo.document_type_names(conn))
    repo.replace(conn, states)
    # The structural roles saved here are now authoritative, so drop any stale
    # per-transition role overrides (legacy app_config layer) that would shadow
    # them and could reference transitions this edit removed.
    appconfig.set_transition_role_overrides(conn, {})
    return from_db(conn)


def _validate(states: list[dict], doc_types: set[str]) -> None:
    if not states:
        raise StateError("Workflow must define at least one state.")

    names = [(s.get("name") or "").strip() for s in states]
    if any(not n for n in names):
        raise StateError("Every state must have a name.")
    if len(set(names)) != len(names):
        raise StateError("State names must be unique.")
    known_states = set(names)

    for state in states:
        seen: set[str] = set()
        for t in state.get("transitions") or []:
            tname = (t.get("name") or "").strip()
            if not tname:
                raise StateError(f"State '{state['name']}' has a transition without a name.")
            if tname in seen:
                raise StateError(f"State '{state['name']}' has duplicate transition '{tname}'.")
            seen.add(tname)

            target = t.get("target")
            if target not in known_states:
                raise StateError(
                    f"Transition '{tname}' from '{state['name']}' targets unknown "
                    f"state '{target}'."
                )

            bad_roles = set(t.get("roles") or []) - ALL_ROLES
            if bad_roles:
                raise StateError(f"Unknown role(s): {', '.join(sorted(bad_roles))}.")

            for guard in t.get("requires") or []:
                if is_document_guard(guard):
                    doc_type = document_guard_type(guard)
                    if doc_type not in doc_types:
                        raise StateError(
                            f'Unknown document type "{doc_type}" in guard "{guard}". '
                            f"Configure it under Document types first."
                        )
                elif guard not in KNOWN_GUARDS:
                    raise StateError(
                        f'Unknown readiness guard "{guard}". Allowed: '
                        f"{', '.join(sorted(KNOWN_GUARDS))}, or document:<TypeName>."
                    )
