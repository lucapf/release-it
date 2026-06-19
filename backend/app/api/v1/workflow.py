"""/api/v1/workflow — the configurable, database-backed release state graph.

The graph is persisted (see migration 0006) and seeded from states.yaml. Clients
read it to render the workflow and to offer an operator only the transitions
allowed from the current state and permitted for their roles. The backend stays
the source of truth: ``/release/{id}/transition`` re-checks both.

Administrators can replace the whole graph (PUT) or export it as
states.yaml-compatible YAML (GET /export).
"""
from __future__ import annotations

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from app.core.jwt_verify import ROLE_ADMIN, require_role
from app.db.pool import get_conn
from app.schemas.models import (
    Workflow,
    WorkflowState,
    WorkflowTransition,
    WorkflowUpdate,
)
from app.services import appconfig
from app.services import workflow as workflow_svc
from app.services.state_machine import StateError, StateMachine

router = APIRouter()


def get_state_machine(request: Request) -> StateMachine:
    return request.app.state.state_machine


def _serialize(sm: StateMachine, conn: psycopg.Connection) -> Workflow:
    """Render the state machine with each transition's *effective* roles (admin
    override > structural > default), so clients can gate actions correctly."""
    states = [
        WorkflowState(
            name=state.name,
            score=state.score,
            is_final=state.is_final,
            transitions=[
                WorkflowTransition(
                    name=t.name,
                    target=t.target,
                    roles=sorted(appconfig.transition_roles(conn, sm, state.name, t.name)),
                    requires=sorted(t.requires),
                )
                for t in state.transitions.values()
            ],
        )
        for state in sm.states()
    ]
    return Workflow(initial_state=sm.initial_state, states=states)


@router.get("", response_model=Workflow)
def get_workflow(
    sm: StateMachine = Depends(get_state_machine),
    conn: psycopg.Connection = Depends(get_conn),
):
    return _serialize(sm, conn)


@router.get("/export")
def export_workflow(conn: psycopg.Connection = Depends(get_conn)):
    """The persisted workflow as states.yaml-compatible YAML (downloadable)."""
    yaml_text = workflow_svc.export_yaml(conn)
    return Response(
        content=yaml_text,
        media_type="application/x-yaml",
        headers={"Content-Disposition": 'attachment; filename="states.yaml"'},
    )


@router.put("", response_model=Workflow,
            dependencies=[Depends(require_role(ROLE_ADMIN))])
def update_workflow(
    body: WorkflowUpdate,
    request: Request,
    conn: psycopg.Connection = Depends(get_conn),
):
    """Replace the entire workflow graph. Persists the new definition, rebuilds
    the in-memory state machine, and returns the effective workflow."""
    states = [
        {
            "name": s.name,
            "transitions": [
                {"name": t.name, "target": t.target, "roles": t.roles, "requires": t.requires}
                for t in s.transitions
            ],
        }
        for s in body.states
    ]
    try:
        sm = workflow_svc.replace(conn, states)
    except StateError as exc:
        raise HTTPException(400, str(exc)) from exc
    # Swap the live state machine so subsequent requests see the new graph.
    request.app.state.state_machine = sm
    return _serialize(sm, conn)
