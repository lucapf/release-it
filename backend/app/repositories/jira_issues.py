"""Tracked-issue data access — raw parametrized SQL via psycopg3.

Issues are fetched through :mod:`app.integrations.trackers` (Jira or GitHub) and
cached per release so the UI can display the "contained issues" without
re-querying the tracker every time.
"""
from __future__ import annotations

import psycopg

_COLS = "id, release_id, issue_key, issue_type, summary, status, synced_at"


def replace_for_release(
    conn: psycopg.Connection, release_id: int, issues: list[dict]
) -> list[dict]:
    """Replace the cached issue set for a release with a freshly fetched one.

    A sync is authoritative: issues that disappeared from the query result are
    dropped. Returns the stored rows ordered by issue key.
    """
    conn.execute("DELETE FROM jira_issue WHERE release_id = %s", (release_id,))
    for issue in issues:
        conn.execute(
            """
            INSERT INTO jira_issue (release_id, issue_key, issue_type, summary, status)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (release_id, issue_key) DO UPDATE
                SET issue_type = EXCLUDED.issue_type,
                    summary    = EXCLUDED.summary,
                    status     = EXCLUDED.status,
                    synced_at  = now()
            """,
            (
                release_id,
                issue.get("key", ""),
                issue.get("type", "Task"),
                issue.get("summary", ""),
                issue.get("status", ""),
            ),
        )
    return list_by_release(conn, release_id)


def list_by_release(conn: psycopg.Connection, release_id: int) -> list[dict]:
    return conn.execute(
        f"SELECT {_COLS} FROM jira_issue WHERE release_id = %s ORDER BY issue_key",
        (release_id,),
    ).fetchall()
