"""Release-workflow graph persistence — states + transitions (raw SQL)."""
from __future__ import annotations

import psycopg


def load(conn: psycopg.Connection) -> list[dict]:
    """All states ordered by score, each carrying its transitions (in position
    order). Shape: ``[{name, score, transitions: [{name, target, roles, requires}]}]``."""
    states = conn.execute(
        "SELECT name, score FROM workflow_state ORDER BY score"
    ).fetchall()
    transitions = conn.execute(
        "SELECT state, name, target, roles, requires "
        "FROM workflow_transition ORDER BY state, position"
    ).fetchall()

    by_state: dict[str, list[dict]] = {}
    for t in transitions:
        by_state.setdefault(t["state"], []).append(
            {"name": t["name"], "target": t["target"],
             "roles": list(t["roles"]), "requires": list(t["requires"])}
        )
    for s in states:
        s["transitions"] = by_state.get(s["name"], [])
    return states


def replace(conn: psycopg.Connection, states: list[dict]) -> None:
    """Rewrite the whole graph from an ordered list of states. Each entry is
    ``{name, transitions: [{name, target, roles, requires}]}``; the list order
    defines each state's score (so the first state is the initial one) and each
    transition's position. The caller's transaction makes this atomic."""
    conn.execute("DELETE FROM workflow_transition")
    conn.execute("DELETE FROM workflow_state")
    # Insert all states first so transition order is unconstrained by targets.
    for score, st in enumerate(states):
        conn.execute(
            "INSERT INTO workflow_state (name, score) VALUES (%s, %s)",
            (st["name"], score),
        )
    for st in states:
        for pos, t in enumerate(st.get("transitions") or []):
            conn.execute(
                "INSERT INTO workflow_transition "
                "(state, name, target, roles, requires, position) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (st["name"], t["name"], t["target"],
                 list(t.get("roles") or []), list(t.get("requires") or []), pos),
            )
