"""Pydantic request/response models. Rows from psycopg (dict_row) map directly."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Phase = Literal["pre", "post"]


# --- Product ---------------------------------------------------------------
class ProductCreate(BaseModel):
    name: str
    solution_id: int | None = None


class Product(BaseModel):
    id: int
    name: str
    solution_id: int | None = None
    created_at: datetime


# --- Release ---------------------------------------------------------------
class ReleaseCreate(BaseModel):
    product_id: int
    version: str
    short_description: str = ""


class Release(BaseModel):
    id: int
    product_id: int
    version: str
    state: str
    short_description: str
    parent_release_id: int | None = None
    created_at: datetime


class ProductOverview(BaseModel):
    """Dashboard row: a product plus its current draft / under-approval release."""
    id: int
    name: str
    solution_id: int | None = None
    created_at: datetime
    release_count: int = 0
    draft: Release | None = None
    under_approval: Release | None = None


class TransitionRequest(BaseModel):
    transition: str = Field(..., description="Name of the transition to apply, e.g. 'Approve'")


class InheritRequest(BaseModel):
    version: str = Field(..., description="Version for the new inherited release")


# --- Check -----------------------------------------------------------------
class CheckCreate(BaseModel):
    label: str
    phase: Phase


class Check(BaseModel):
    id: int
    release_id: int
    label: str
    phase: Phase
    done: bool
    created_at: datetime


class CheckUpdate(BaseModel):
    done: bool


# --- Environment -----------------------------------------------------------
class EnvironmentCreate(BaseModel):
    name: str
    description: str = ""


class Environment(BaseModel):
    id: int
    name: str
    description: str
    created_at: datetime


# --- Artifact / Documentation (metadata only; content streamed separately) -
class ArtifactMeta(BaseModel):
    id: int
    release_id: int
    name: str
    content_type: str
    created_at: datetime


class DocumentationMeta(BaseModel):
    id: int
    release_id: int
    name: str
    content_type: str
    is_draft: bool
    created_at: datetime


# --- Jira integration ------------------------------------------------------
class JiraSyncRequest(BaseModel):
    """Filter for a Jira sync. Provide a custom JQL query, or a release label
    (mapped to ``labels = "<label>"``). If neither is given the release version
    is used (``fixVersion = "<version>"``)."""
    release_label: str | None = Field(default=None, description="Jira label to filter by")
    jql: str | None = Field(default=None, description="Raw JQL query (takes precedence)")


class JiraIssue(BaseModel):
    id: int
    release_id: int
    issue_key: str
    issue_type: str
    summary: str
    status: str
    synced_at: datetime


# --- Audit -----------------------------------------------------------------
class AuditEntry(BaseModel):
    id: int
    entity_type: str
    entity_id: int
    action: str
    old_value: str | None
    new_value: str | None
    operator: str | None
    created_at: datetime
