"""/api/v1/product — product management + list its releases."""
from __future__ import annotations

import psycopg
from psycopg import errors as pg_errors
from fastapi import APIRouter, Depends, HTTPException

from app.db.pool import get_conn
from app.integrations import trackers
from app.integrations.trackers import (
    TrackerNotConfigured,
    TrackerProjectNotFound,
    TrackerUnreachable,
)
from app.repositories import products as repo
from app.repositories import releases as releases_repo
from app.schemas.models import (
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
