"""/api/v1/environment — environment CRUD."""
from __future__ import annotations

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from app.core.jwt_verify import ROLE_ADMIN, ROLE_RELEASE_MANAGER, require_role
from app.db.pool import get_conn
from app.repositories import environments as repo
from app.schemas.models import Environment, EnvironmentCreate

router = APIRouter()


@router.get("", response_model=list[Environment])
def list_environments(conn: psycopg.Connection = Depends(get_conn)):
    return repo.list_all(conn)


@router.post("", response_model=Environment, status_code=201,
             dependencies=[Depends(require_role(ROLE_ADMIN, ROLE_RELEASE_MANAGER))])
def create_environment(body: EnvironmentCreate, conn: psycopg.Connection = Depends(get_conn)):
    return repo.create(conn, body.name, body.description)


@router.get("/{env_id}", response_model=Environment)
def get_environment(env_id: int, conn: psycopg.Connection = Depends(get_conn)):
    row = repo.get(conn, env_id)
    if row is None:
        raise HTTPException(404, "Environment not found")
    return row


@router.put("/{env_id}", response_model=Environment,
            dependencies=[Depends(require_role(ROLE_ADMIN, ROLE_RELEASE_MANAGER))])
def update_environment(env_id: int, body: EnvironmentCreate,
                       conn: psycopg.Connection = Depends(get_conn)):
    row = repo.update(conn, env_id, body.name, body.description)
    if row is None:
        raise HTTPException(404, "Environment not found")
    return row


@router.delete("/{env_id}", status_code=204,
               dependencies=[Depends(require_role(ROLE_ADMIN))])
def delete_environment(env_id: int, conn: psycopg.Connection = Depends(get_conn)):
    if not repo.delete(conn, env_id):
        raise HTTPException(404, "Environment not found")
