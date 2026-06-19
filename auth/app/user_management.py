"""/api/v1/user-management — login, user CRUD, role management."""
from __future__ import annotations

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db import get_conn
from app.deps import ADMIN_ROLE, require_admin
from app.security import hash_password, issue_token, verify_password
from app import users_repo as repo

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserCreate(BaseModel):
    username: str
    password: str
    email: str | None = None
    roles: list[str] = []


class UserUpdate(BaseModel):
    email: str | None = None
    # When provided, replaces the user's role set entirely. Omit to leave roles
    # unchanged (an empty list explicitly clears all roles).
    roles: list[str] | None = None


class RoleCreate(BaseModel):
    name: str


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, conn: psycopg.Connection = Depends(get_conn)):
    user = repo.get_by_username(conn, body.username)
    if user is None or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Invalid credentials")
    roles = repo.roles_for_user(conn, user["id"])
    return TokenResponse(access_token=issue_token(user["username"], roles))


@router.get("/users", dependencies=[Depends(require_admin)])
def list_users(conn: psycopg.Connection = Depends(get_conn)):
    users = repo.list_users(conn)
    for u in users:
        u["roles"] = repo.roles_for_user(conn, u["id"])
    return users


@router.post("/users", status_code=201, dependencies=[Depends(require_admin)])
def create_user(body: UserCreate, conn: psycopg.Connection = Depends(get_conn)):
    if repo.get_by_username(conn, body.username):
        raise HTTPException(409, "Username already exists")
    user = repo.create_user(conn, body.username, body.email, hash_password(body.password))
    for role in body.roles:
        repo.assign_role(conn, user["id"], role)
    user["roles"] = repo.roles_for_user(conn, user["id"])
    return user


@router.put("/users/{user_id}")
def update_user(
    user_id: int,
    body: UserUpdate,
    caller: str = Depends(require_admin),
    conn: psycopg.Connection = Depends(get_conn),
):
    user = repo.get_user(conn, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    # Only touch the email when the field was explicitly supplied, so a
    # roles-only update doesn't wipe an existing address.
    if "email" in body.model_fields_set:
        repo.update_user(conn, user_id, body.email)
    if body.roles is not None:
        had_admin = ADMIN_ROLE in repo.roles_for_user(conn, user_id)
        losing_admin = had_admin and ADMIN_ROLE not in body.roles
        if losing_admin and repo.count_admins(conn) <= 1:
            raise HTTPException(409, "Cannot remove the last administrator")
        repo.set_roles(conn, user_id, body.roles)
    user = repo.get_user(conn, user_id)
    user["roles"] = repo.roles_for_user(conn, user_id)
    return user


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    caller: str = Depends(require_admin),
    conn: psycopg.Connection = Depends(get_conn),
):
    user = repo.get_user(conn, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    if user["username"] == caller:
        raise HTTPException(400, "You cannot delete your own account")
    if ADMIN_ROLE in repo.roles_for_user(conn, user_id) and repo.count_admins(conn) <= 1:
        raise HTTPException(409, "Cannot delete the last administrator")
    repo.delete_user(conn, user_id)


@router.get("/roles", dependencies=[Depends(require_admin)])
def list_roles(conn: psycopg.Connection = Depends(get_conn)):
    return repo.list_roles(conn)


@router.post("/roles", status_code=201, dependencies=[Depends(require_admin)])
def create_role(body: RoleCreate, conn: psycopg.Connection = Depends(get_conn)):
    return repo.create_role(conn, body.name)


@router.delete("/roles/{role_id}", status_code=204, dependencies=[Depends(require_admin)])
def delete_role(role_id: int, conn: psycopg.Connection = Depends(get_conn)):
    if not repo.delete_role(conn, role_id):
        raise HTTPException(404, "Role not found")
