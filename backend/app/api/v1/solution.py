"""/api/v1/solution — optional feature, mounted only when SOLUTION_ENABLED.

The solution's derived state equals the *least-advanced* product state (lowest
score in the state machine), per docs/release-it.md.
"""
from __future__ import annotations

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.core.jwt_verify import ROLE_ADMIN, ROLE_RELEASE_MANAGER, require_role
from app.db.pool import get_conn
from app.repositories import solutions as repo
from app.services.state_machine import StateMachine

router = APIRouter()


class SolutionCreate(BaseModel):
    name: str
    version: str


class SolutionState(BaseModel):
    id: int
    name: str
    version: str
    derived_state: str | None
    products: list[dict]
    checks: list[dict]


def get_state_machine(request: Request) -> StateMachine:
    return request.app.state.state_machine


@router.get("")
def list_solutions(conn: psycopg.Connection = Depends(get_conn)):
    return repo.list_all(conn)


@router.post("", status_code=201,
             dependencies=[Depends(require_role(ROLE_ADMIN, ROLE_RELEASE_MANAGER))])
def create_solution(body: SolutionCreate, conn: psycopg.Connection = Depends(get_conn)):
    return repo.create(conn, body.name, body.version)


@router.get("/{solution_id}", response_model=SolutionState)
def get_solution(
    solution_id: int,
    conn: psycopg.Connection = Depends(get_conn),
    sm: StateMachine = Depends(get_state_machine),
):
    sol = repo.get(conn, solution_id)
    if sol is None:
        raise HTTPException(404, "Solution not found")

    product_states = repo.latest_release_states(conn, solution_id)
    # Derived state = the least-advanced (lowest-score) known product state.
    known = [p for p in product_states if sm.exists(p["state"])]
    derived = min(known, key=lambda p: sm.score(p["state"]))["state"] if known else None

    return SolutionState(
        id=sol["id"], name=sol["name"], version=sol["version"],
        derived_state=derived, products=product_states,
        checks=repo.union_checks(conn, solution_id),
    )
