"""The Solution entity is not part of the current release and must stay removed.

Migration 0014 drops the ``solution`` table and ``product.solution_id``, so any
surviving reference to either would only fail at runtime against a real database
(an UndefinedColumn/UndefinedTable error). These tests catch that statically: no
database is involved — the product SQL is captured with a fake connection.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from app.repositories import products as repo
from app.schemas.models import Product, ProductCreate, ProductOverview

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


class _FakeCursor:
    rowcount = 0

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class _FakeConn:
    """Captures the SQL the repository emits instead of executing it."""

    def __init__(self):
        self.sql: list[str] = []

    def execute(self, sql, params=None):
        self.sql.append(str(sql))
        return _FakeCursor()


def _emitted_sql() -> str:
    """Every statement the product repository can issue, concatenated."""
    conn = _FakeConn()
    repo.create(conn, "p", "owner/repo")
    repo.get(conn, 1)
    repo.list_all(conn)
    repo.update(conn, 1, name="p2", tracker_repo="o/r2")
    repo.overview(conn)
    repo.delete(conn, 1)
    return "\n".join(conn.sql).lower()


def test_product_sql_never_references_solution():
    sql = _emitted_sql()
    assert "solution_id" not in sql
    assert "solution" not in sql


def test_product_schemas_have_no_solution_field():
    for model in (Product, ProductCreate, ProductOverview):
        assert "solution_id" not in model.model_fields


def test_creating_a_product_takes_no_solution():
    """The API layer calls repo.create(conn, name, tracker_repo) positionally."""
    conn = _FakeConn()
    repo.create(conn, "p", "owner/repo")
    assert "INSERT INTO product (name, tracker_repo)" in conn.sql[0]


def test_product_create_rejects_a_solution_id():
    """A client still sending solution_id gets no silently-ignored field."""
    body = ProductCreate.model_validate({"name": "p", "solution_id": 7})
    assert not hasattr(body, "solution_id")


@pytest.mark.parametrize(
    "module",
    ["app.api.v1.solution", "app.repositories.solutions"],
)
def test_solution_modules_are_gone(module):
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module)


def test_app_exposes_no_solution_routes():
    from app.main import app

    assert not [r for r in app.routes if "solution" in getattr(r, "path", "")]


def test_settings_have_no_solution_feature_flag():
    from app.core.config import settings

    assert "solution_enabled" not in type(settings).model_fields


def test_migration_drops_the_solution_table_and_column():
    sql = (MIGRATIONS / "0014_drop_solution.sql").read_text().lower()
    assert "drop column if exists solution_id" in sql
    assert "drop table if exists solution" in sql


def test_no_later_migration_reintroduces_solution():
    """0001 creates the table (history, never edited); nothing after 0014 revives it."""
    for path in sorted(MIGRATIONS.glob("*.sql")):
        if path.name <= "0014_drop_solution.sql":
            continue
        assert "solution" not in path.read_text().lower(), path.name
