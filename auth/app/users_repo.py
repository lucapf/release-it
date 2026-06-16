"""User & role data access for releaseit-auth."""
from __future__ import annotations

import psycopg


def count_users(conn: psycopg.Connection) -> int:
    return conn.execute("SELECT count(*) AS n FROM app_user").fetchone()["n"]


def create_user(conn: psycopg.Connection, username: str, email: str | None, password_hash: str) -> dict:
    return conn.execute(
        """
        INSERT INTO app_user (username, email, password_hash)
        VALUES (%s, %s, %s)
        RETURNING id, username, email, created_at
        """,
        (username, email, password_hash),
    ).fetchone()


def get_by_username(conn: psycopg.Connection, username: str) -> dict | None:
    return conn.execute(
        "SELECT id, username, email, password_hash FROM app_user WHERE username = %s",
        (username,),
    ).fetchone()


def list_users(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(
        "SELECT id, username, email, created_at FROM app_user ORDER BY username"
    ).fetchall()


def update_user(conn: psycopg.Connection, user_id: int, email: str | None) -> dict | None:
    return conn.execute(
        "UPDATE app_user SET email = %s WHERE id = %s RETURNING id, username, email, created_at",
        (email, user_id),
    ).fetchone()


def delete_user(conn: psycopg.Connection, user_id: int) -> bool:
    return conn.execute("DELETE FROM app_user WHERE id = %s", (user_id,)).rowcount > 0


def roles_for_user(conn: psycopg.Connection, user_id: int) -> list[str]:
    rows = conn.execute(
        """
        SELECT r.name FROM role r
        JOIN user_role ur ON ur.role_id = r.id
        WHERE ur.user_id = %s ORDER BY r.name
        """,
        (user_id,),
    ).fetchall()
    return [r["name"] for r in rows]


def assign_role(conn: psycopg.Connection, user_id: int, role_name: str) -> None:
    conn.execute(
        """
        INSERT INTO user_role (user_id, role_id)
        SELECT %s, id FROM role WHERE name = %s
        ON CONFLICT DO NOTHING
        """,
        (user_id, role_name),
    )


# --- Roles -----------------------------------------------------------------
def list_roles(conn: psycopg.Connection) -> list[dict]:
    return conn.execute("SELECT id, name FROM role ORDER BY name").fetchall()


def create_role(conn: psycopg.Connection, name: str) -> dict:
    return conn.execute(
        "INSERT INTO role (name) VALUES (%s) RETURNING id, name", (name,)
    ).fetchone()


def delete_role(conn: psycopg.Connection, role_id: int) -> bool:
    return conn.execute("DELETE FROM role WHERE id = %s", (role_id,)).rowcount > 0
