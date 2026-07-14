"""/api/v1/product — product management + list its releases."""
from __future__ import annotations

import psycopg
from psycopg import errors as pg_errors
from fastapi import APIRouter, Depends, HTTPException

from app.db.pool import get_conn
from app.integrations import git, trackers
from app.integrations.git import (
    GitNotConfigured,
    GitRepoNotFound,
    GitUnreachable,
)
from app.integrations.trackers import (
    TrackerNotConfigured,
    TrackerProjectNotFound,
    TrackerUnreachable,
)
from app.repositories import git_repos as git_repos_repo
from app.repositories import products as repo
from app.repositories import releases as releases_repo
from app.schemas.models import (
    GitRepoLink,
    GitRepoLinkCreate,
    GitRepoLinkUpdate,
    Product,
    ProductCreate,
    ProductOverview,
    ProductUpdate,
    Release,
)
from app.services import appconfig

router = APIRouter()


def _verify_tracker_project(conn: psycopg.Connection, tracker_repo: str | None) -> None:
    """Confirm the issue-tracker project bound to a product actually exists,
    rejecting the save with a clear message when it does not, when the tracker is
    unreachable, or when there is no tracker to ask.

    A binding nobody checked must not end up looking like one that passed: with no
    tracker enabled, every value verifies vacuously and the product is saved
    pointing at a repository that may not exist. So a project can only be bound
    once the tracker that has to answer for it is configured. Clearing the binding
    is always allowed — an empty value asks the tracker nothing.
    """
    repo_val = (tracker_repo or "").strip()
    if not repo_val:
        return
    cfg = appconfig.effective(conn)
    try:
        trackers.require_configured(cfg)
    except TrackerNotConfigured as exc:
        # Deliberately not named after the active provider: with no tracker
        # enabled the provider is just the default, and telling someone who typed
        # a GitHub repo that their "Jira project" cannot be verified is nonsense.
        raise HTTPException(
            400,
            f'Cannot verify the issue-tracker project "{repo_val}": no issue tracker '
            "is enabled and configured. Set up the tracker on the Configuration page "
            "first, or leave this project's issue tracker field empty.",
        ) from exc

    label = "GitHub repository" if cfg.provider == "github" else "Jira project"
    try:
        trackers.verify_project(cfg, repo_val)
    except TrackerProjectNotFound as exc:
        raise HTTPException(
            400, f'The {label} "{repo_val}" was not found on the configured tracker.'
        ) from exc
    except TrackerUnreachable as exc:
        raise HTTPException(
            502, f'Could not reach the tracker to verify "{repo_val}": {exc}'
        ) from exc


@router.get("", response_model=list[Product])
def list_products(conn: psycopg.Connection = Depends(get_conn)):
    return repo.list_all(conn)


@router.get("/overview", response_model=list[ProductOverview])
def products_overview(conn: psycopg.Connection = Depends(get_conn)):
    """Dashboard feed: every product with its current draft and under-approval
    release. Declared before ``/{product_id}`` so it isn't shadowed by it."""
    return repo.overview(conn)


@router.post("", response_model=Product, status_code=201)
def create_product(body: ProductCreate, conn: psycopg.Connection = Depends(get_conn)):
    _verify_tracker_project(conn, body.tracker_repo)
    return repo.create(conn, body.name, body.tracker_repo)


@router.get("/{product_id}", response_model=Product)
def get_product(product_id: int, conn: psycopg.Connection = Depends(get_conn)):
    row = repo.get(conn, product_id)
    if row is None:
        raise HTTPException(404, "Product not found")
    return row


@router.patch("/{product_id}", response_model=Product)
def update_product(
    product_id: int, body: ProductUpdate, conn: psycopg.Connection = Depends(get_conn)
):
    """Update a product's editable settings: its name and/or its issue-tracker
    project (e.g. the GitHub repository). Omitted fields are left unchanged."""
    if repo.get(conn, product_id) is None:
        raise HTTPException(404, "Product not found")

    name = body.name.strip() if body.name is not None else None
    if name is not None and not name:
        raise HTTPException(422, "Product name cannot be empty")
    tracker_repo = body.tracker_repo.strip() if body.tracker_repo is not None else None
    if tracker_repo is not None:
        _verify_tracker_project(conn, tracker_repo)

    try:
        return repo.update(conn, product_id, name=name, tracker_repo=tracker_repo)
    except pg_errors.UniqueViolation as exc:
        raise HTTPException(409, "A product with that name already exists") from exc


@router.get("/{product_id}/releases", response_model=list[Release])
def list_product_releases(product_id: int, conn: psycopg.Connection = Depends(get_conn)):
    if repo.get(conn, product_id) is None:
        raise HTTPException(404, "Product not found")
    return releases_repo.list_by_product(conn, product_id)


@router.delete("/{product_id}", status_code=204)
def delete_product(product_id: int, conn: psycopg.Connection = Depends(get_conn)):
    if not repo.delete(conn, product_id):
        raise HTTPException(404, "Product not found")


# --- Git repository links ----------------------------------------------------
def _verify_git_repo(conn: psycopg.Connection, provider: str, repo_path: str) -> None:
    """Confirm a repository exists on its git hosting before saving the link.

    Same fail-closed stance as the tracker binding: a link nobody checked must
    not look like one that passed, so a repository can only be linked once the
    connection that has to answer for it is configured.
    """
    cfg = appconfig.effective(conn)
    try:
        git.get_git_provider(cfg, provider).verify_repo(repo_path)
    except GitNotConfigured as exc:
        raise HTTPException(
            400,
            f'Cannot verify the repository "{repo_path}": the {provider} git '
            "connection is not enabled and configured. Set it up on the "
            "Configuration page first.",
        ) from exc
    except GitRepoNotFound as exc:
        raise HTTPException(
            400, f'The repository "{repo_path}" was not found on {provider}.'
        ) from exc
    except GitUnreachable as exc:
        raise HTTPException(
            502, f'Could not reach {provider} to verify "{repo_path}": {exc}'
        ) from exc


def _friendly_link_conflict(exc: pg_errors.UniqueViolation) -> HTTPException:
    name = (exc.diag.constraint_name or "") if exc.diag else ""
    if "one_deployment" in name:
        return HTTPException(
            409, "This product already has a deployment (umbrella chart) repository."
        )
    if "component_name" in name:
        return HTTPException(
            409, "This product already has a component with that name."
        )
    return HTTPException(409, "This repository is already linked to the product.")


def _clean_link_fields(role: str, component_name: str) -> str:
    """Validate the role/component_name pairing, mirroring the DB CHECK with a
    message an operator can act on. Returns the normalized component name."""
    component_name = component_name.strip()
    if role == "component" and not component_name:
        raise HTTPException(
            422,
            "A component repository needs a component name — the dependency "
            "name it appears under in the umbrella Chart.yaml.",
        )
    return component_name


@router.get("/{product_id}/git-repos", response_model=list[GitRepoLink])
def list_git_repos(product_id: int, conn: psycopg.Connection = Depends(get_conn)):
    if repo.get(conn, product_id) is None:
        raise HTTPException(404, "Product not found")
    return git_repos_repo.list_for_product(conn, product_id)


@router.post("/{product_id}/git-repos", response_model=GitRepoLink, status_code=201)
def add_git_repo(
    product_id: int, body: GitRepoLinkCreate, conn: psycopg.Connection = Depends(get_conn)
):
    if repo.get(conn, product_id) is None:
        raise HTTPException(404, "Product not found")
    repo_path = body.repo.strip()
    component_name = _clean_link_fields(body.role, body.component_name)
    _verify_git_repo(conn, body.provider, repo_path)
    try:
        return git_repos_repo.create(
            conn,
            product_id=product_id,
            provider=body.provider,
            repo=repo_path,
            role=body.role,
            component_name=component_name if body.role == "component" else "",
            tag_pattern=body.tag_pattern.strip() or "v{version}",
            web_url=body.web_url.strip(),
            chart_path=body.chart_path.strip() or "Chart.yaml",
        )
    except pg_errors.UniqueViolation as exc:
        raise _friendly_link_conflict(exc) from exc


@router.patch("/{product_id}/git-repos/{link_id}", response_model=GitRepoLink)
def update_git_repo(
    product_id: int,
    link_id: int,
    body: GitRepoLinkUpdate,
    conn: psycopg.Connection = Depends(get_conn),
):
    existing = git_repos_repo.get(conn, link_id)
    if existing is None or existing["product_id"] != product_id:
        raise HTTPException(404, "Repository link not found")

    provider = body.provider if body.provider is not None else existing["provider"]
    repo_path = (body.repo if body.repo is not None else existing["repo"]).strip()
    role = body.role if body.role is not None else existing["role"]
    component_name = _clean_link_fields(
        role,
        body.component_name
        if body.component_name is not None
        else existing["component_name"],
    )
    # Re-verify whenever the repository or its provider changes.
    if repo_path != existing["repo"] or provider != existing["provider"]:
        _verify_git_repo(conn, provider, repo_path)

    try:
        return git_repos_repo.update(
            conn,
            link_id,
            provider=provider,
            repo=repo_path,
            role=role,
            component_name=component_name if role == "component" else "",
            tag_pattern=body.tag_pattern.strip() if body.tag_pattern is not None else None,
            web_url=body.web_url.strip() if body.web_url is not None else None,
            chart_path=body.chart_path.strip() if body.chart_path is not None else None,
        )
    except pg_errors.UniqueViolation as exc:
        raise _friendly_link_conflict(exc) from exc


@router.delete("/{product_id}/git-repos/{link_id}", status_code=204)
def delete_git_repo(
    product_id: int, link_id: int, conn: psycopg.Connection = Depends(get_conn)
):
    existing = git_repos_repo.get(conn, link_id)
    if existing is None or existing["product_id"] != product_id:
        raise HTTPException(404, "Repository link not found")
    git_repos_repo.delete(conn, link_id)
