"""Plain-SQL migration runner.

Applies versioned ``.sql`` files from the ``migrations/`` directory in order.
Each file is split into individual statements with ``sqlparse.split()`` and
executed via psycopg3. Applied versions are recorded in ``schema_migrations``
so re-running is idempotent.

Usage:
    python -m app.db.migrate            # apply pending migrations
    python -m app.db.migrate --status   # list applied / pending
"""
from __future__ import annotations

import sys
from pathlib import Path

import sqlparse

from app.db.pool import close_pool, connection, open_pool

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

_ENSURE_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def _migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"), key=lambda p: p.name)


def _applied_versions(conn) -> set[str]:
    conn.execute(_ENSURE_TABLE)
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {r["version"] for r in rows}


def apply_pending() -> list[str]:
    """Apply all migration files not yet recorded. Returns applied versions."""
    applied: list[str] = []
    with connection() as conn:
        done = _applied_versions(conn)
        for path in _migration_files():
            version = path.stem
            if version in done:
                continue
            sql = path.read_text(encoding="utf-8")
            for statement in sqlparse.split(sql):
                stmt = statement.strip()
                if stmt:
                    conn.execute(stmt)
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s)", (version,)
            )
            applied.append(version)
        conn.commit()
    return applied


def status() -> tuple[set[str], list[str]]:
    with connection() as conn:
        done = _applied_versions(conn)
    pending = [p.stem for p in _migration_files() if p.stem not in done]
    return done, pending


def main(argv: list[str]) -> int:
    open_pool()
    try:
        if "--status" in argv:
            done, pending = status()
            print(f"Applied ({len(done)}): {sorted(done)}")
            print(f"Pending ({len(pending)}): {pending}")
        else:
            applied = apply_pending()
            print(f"Applied {len(applied)} migration(s): {applied}" if applied else "Up to date.")
        return 0
    finally:
        close_pool()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
