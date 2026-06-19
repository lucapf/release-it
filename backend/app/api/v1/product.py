"""/api/v1/product — product management + list its releases."""
from __future__ import annotations

import psycopg
from psycopg import errors as pg_errors
from fastapi import APIRouter, Depends, HTTPException

from app.core.jwt_verify import (
    ROLE_ADMIN,
    ROLE_DEVELOPER,
    ROLE_RELEASE_MANAGER,
    require_role,
)
from app.db.pool import get_conn
from app.repositories import products as repo
from app.repositories import releases as releases_repo
from app.schemas.models import (
    Product,
    ProductCreate,
    ProductOverview,
    ProductUpdate,
    Release,
)

router = APIRouter()


@router.get("", response_model=list[Product])
def list_products(conn: psycopg.Connection = Depends(get_conn)):
    return repo.list_all(conn)


@router.get("/overview", response_model=list[ProductOverview])
def products_overview(conn: psycopg.Connection = Depends(get_conn)):
    """Dashboard feed: every product with its current draft and under-approval
    release. Declared before ``/{product_id}`` so it isn't shadowed by it."""
    return repo.overview(conn)


@router.post("", response_model=Product, status_code=201,
             dependencies=[Depends(require_role(ROLE_DEVELOPER, ROLE_RELEASE_MANAGER, ROLE_ADMIN))])
def create_product(body: ProductCreate, conn: psycopg.Connection = Depends(get_conn)):
    return repo.create(conn, body.name, body.solution_id, body.tracker_repo)


@router.get("/{product_id}", response_model=Product)
def get_product(product_id: int, conn: psycopg.Connection = Depends(get_conn)):
    row = repo.get(conn, product_id)
    if row is None:
        raise HTTPException(404, "Product not found")
    return row


@router.patch("/{product_id}", response_model=Product,
              dependencies=[Depends(require_role(ROLE_DEVELOPER, ROLE_RELEASE_MANAGER, ROLE_ADMIN))])
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

    try:
        return repo.update(conn, product_id, name=name, tracker_repo=tracker_repo)
    except pg_errors.UniqueViolation as exc:
        raise HTTPException(409, "A product with that name already exists") from exc


@router.get("/{product_id}/releases", response_model=list[Release])
def list_product_releases(product_id: int, conn: psycopg.Connection = Depends(get_conn)):
    if repo.get(conn, product_id) is None:
        raise HTTPException(404, "Product not found")
    return releases_repo.list_by_product(conn, product_id)


@router.delete("/{product_id}", status_code=204,
               dependencies=[Depends(require_role(ROLE_ADMIN))])
def delete_product(product_id: int, conn: psycopg.Connection = Depends(get_conn)):
    if not repo.delete(conn, product_id):
        raise HTTPException(404, "Product not found")
