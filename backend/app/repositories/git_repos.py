"""Product git-repository links — raw parametrized SQL via psycopg3."""
from __future__ import annotations

import psycopg

_COLS = (
    "id, product_id, provider, repo, role, component_name, tag_pattern, "
    "web_url, chart_path, created_at"
)


def create(
    conn: psycopg.Connection,
    *,
    product_id: int,
    provider: str,
    repo: str,
    role: str,
    component_name: str = "",
    tag_pattern: str = "v{version}",
    web_url: str = "",
    chart_path: str = "Chart.yaml",
) -> dict:
    return conn.execute(
        f"""
        INSERT INTO product_git_repository
            (product_id, provider, repo, role, component_name, tag_pattern,
             web_url, chart_path)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING {_COLS}
        """,
        (product_id, provider, repo, role, component_name, tag_pattern,
         web_url, chart_path),
    ).fetchone()


def get(conn: psycopg.Connection, link_id: int) -> dict | None:
    return conn.execute(
        f"SELECT {_COLS} FROM product_git_repository WHERE id = %s", (link_id,)
    ).fetchone()


def list_for_product(conn: psycopg.Connection, product_id: int) -> list[dict]:
    """A product's repo links: the anchor repo (deployment/codebase) first,
    then components and libraries by name — the order the UI and reports
    present them in."""
    return conn.execute(
        f"""
        SELECT {_COLS} FROM product_git_repository
        WHERE product_id = %s
        ORDER BY (role NOT IN ('deployment', 'codebase')), role, component_name, repo
        """,
        (product_id,),
    ).fetchall()


def anchor_for(conn: psycopg.Connection, product_id: int) -> dict | None:
    """The repo that anchors the product's versions to git, if one is linked:
    the umbrella chart ('deployment') or, for a simple single-repo product,
    the whole codebase ('codebase'). At most one exists per product."""
    return conn.execute(
        f"""
        SELECT {_COLS} FROM product_git_repository
        WHERE product_id = %s AND role IN ('deployment', 'codebase')
        """,
        (product_id,),
    ).fetchone()


def components_for(conn: psycopg.Connection, product_id: int) -> dict[str, dict]:
    """The product's component repos keyed by their Chart.yaml dependency name."""
    rows = conn.execute(
        f"""
        SELECT {_COLS} FROM product_git_repository
        WHERE product_id = %s AND role = 'component'
        """,
        (product_id,),
    ).fetchall()
    return {r["component_name"]: r for r in rows}


def update(
    conn: psycopg.Connection,
    link_id: int,
    *,
    provider: str | None = None,
    repo: str | None = None,
    role: str | None = None,
    component_name: str | None = None,
    tag_pattern: str | None = None,
    web_url: str | None = None,
    chart_path: str | None = None,
) -> dict | None:
    """Partially update a repo link. Only the provided fields are written."""
    fields = {
        "provider": provider,
        "repo": repo,
        "role": role,
        "component_name": component_name,
        "tag_pattern": tag_pattern,
        "web_url": web_url,
        "chart_path": chart_path,
    }
    sets = [f"{col} = %s" for col, val in fields.items() if val is not None]
    params = [val for val in fields.values() if val is not None]
    if not sets:
        return get(conn, link_id)
    params.append(link_id)
    return conn.execute(
        f"""
        UPDATE product_git_repository SET {', '.join(sets)}
        WHERE id = %s
        RETURNING {_COLS}
        """,
        params,
    ).fetchone()


def delete(conn: psycopg.Connection, link_id: int) -> bool:
    cur = conn.execute(
        "DELETE FROM product_git_repository WHERE id = %s", (link_id,)
    )
    return cur.rowcount > 0
