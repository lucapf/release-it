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
    # Username matching is case-insensitive (login + duplicate detection); the
    # original case is still stored and shown.
    return conn.execute(
        "SELECT id, username, email, password_hash FROM app_user WHERE lower(username) = lower(%s)",
        (username,),
    ).fetchone()


def list_users(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(
        "SELECT id, username, email, created_at FROM app_user ORDER BY username"
    ).fetchall()


def get_user(conn: psycopg.Connection, user_id: int) -> dict | None:
    return conn.execute(
        "SELECT id, username, email, created_at FROM app_user WHERE id = %s",
        (user_id,),
    ).fetchone()


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


def set_roles(conn: psycopg.Connection, user_id: int, roles: list[str]) -> None:
    """Replace a user's role assignments with exactly ``roles``."""
    conn.execute("DELETE FROM user_role WHERE user_id = %s", (user_id,))
    for name in roles:
        assign_role(conn, user_id, name)


def count_admins(conn: psycopg.Connection) -> int:
    """Number of users holding the Administrator role (for lockout guards)."""
    return conn.execute(
        """
        SELECT count(*) AS n FROM user_role ur
        JOIN role r ON r.id = ur.role_id
        WHERE r.name = 'Administrator'
        """
    ).fetchone()["n"]


# --- Roles -----------------------------------------------------------------
def list_roles(conn: psycopg.Connection) -> list[dict]:
    return conn.execute("SELECT id, name FROM role ORDER BY name").fetchall()


def create_role(conn: psycopg.Connection, name: str) -> dict:
    return conn.execute(
        "INSERT INTO role (name) VALUES (%s) RETURNING id, name", (name,)
    ).fetchone()


def delete_role(conn: psycopg.Connection, role_id: int) -> bool:
    return conn.execute("DELETE FROM role WHERE id = %s", (role_id,)).rowcount > 0
