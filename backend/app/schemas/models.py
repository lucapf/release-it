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
    # The product's issue-tracker project, e.g. a GitHub "owner/repo".
    tracker_repo: str = ""


class ProductUpdate(BaseModel):
    """Editable product settings. Only the supplied fields are changed (a field
    left as ``None`` is kept as-is)."""
    name: str | None = None
    tracker_repo: str | None = None


class Product(BaseModel):
    id: int
    name: str
    solution_id: int | None = None
    tracker_repo: str = ""
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
    """Dashboard row: a product plus its last stable, current draft and
    under-approval releases."""
    id: int
    name: str
    solution_id: int | None = None
    tracker_repo: str = ""
    created_at: datetime
    release_count: int = 0
    last_stable: Release | None = None
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


# --- Issue-tracker sync ----------------------------------------------------
class JiraSyncRequest(BaseModel):
    """Filter for an issue sync. The meaningful fields depend on the active
    tracker:

    * Jira   — ``jql`` (raw query, takes precedence) or ``release_label``
      (mapped to ``labels = "<label>"``); otherwise ``fixVersion = "<version>"``.
    * GitHub — ``milestone`` (issues in that milestone; defaults to the release
      version) or ``release_label`` (a GitHub label).
    """
    release_label: str | None = Field(default=None, description="Tracker label to filter by")
    jql: str | None = Field(default=None, description="Jira: raw JQL query (takes precedence)")
    milestone: str | None = Field(default=None, description="GitHub: milestone title (defaults to the release version)")


class JiraIssue(BaseModel):
    id: int
    release_id: int
    issue_key: str
    issue_type: str
    summary: str
    status: str
    synced_at: datetime


# --- Runtime configuration -------------------------------------------------
class JiraConfigView(BaseModel):
    enabled: bool = False
    base_url: str = ""
    token_set: bool = False  # whether a token is stored (never returned raw)


class GitHubConfigView(BaseModel):
    enabled: bool = False
    base_url: str = ""
    token_set: bool = False
    # NOTE: the repository is configured per-product (Product.tracker_repo), not
    # globally, so it is intentionally absent here.


class ClaudeConfigView(BaseModel):
    model: str = ""
    api_key_set: bool = False  # whether an API key is stored (never returned raw)


class OllamaConfigView(BaseModel):
    base_url: str = ""
    model: str = ""


class LLMConfigView(BaseModel):
    provider: str = "claude"
    claude: ClaudeConfigView = ClaudeConfigView()
    ollama: OllamaConfigView = OllamaConfigView()


class ConfigView(BaseModel):
    """Current configuration as shown on the configuration page (no secrets)."""
    tracker_provider: str = "jira"
    jira: JiraConfigView = JiraConfigView()
    github: GitHubConfigView = GitHubConfigView()
    llm: LLMConfigView = LLMConfigView()


class ConfigUpdate(BaseModel):
    """Configuration update. A token/key left as None/empty is kept unchanged,
    so secrets are write-only — they are never echoed back by the API."""
    tracker_provider: Literal["jira", "github"] | None = None
    jira_enabled: bool | None = None
    jira_base_url: str | None = None
    jira_token: str | None = None
    github_enabled: bool | None = None
    github_base_url: str | None = None
    github_token: str | None = None
    # LLM engine
    llm_provider: Literal["claude", "ollama"] | None = None
    claude_model: str | None = None
    claude_api_key: str | None = None
    ollama_base_url: str | None = None
    ollama_model: str | None = None


# --- Check templates (global default checks) -------------------------------
class CheckTemplateCreate(BaseModel):
    label: str
    phase: Phase


class CheckTemplate(BaseModel):
    id: int
    label: str
    phase: Phase
    created_at: datetime


# --- Workflow (state machine exposure) -------------------------------------
class WorkflowTransition(BaseModel):
    name: str
    target: str
    roles: list[str] = []  # roles permitted to perform this transition


class WorkflowState(BaseModel):
    name: str
    score: int
    is_final: bool
    transitions: list[WorkflowTransition] = []


class Workflow(BaseModel):
    """The release state graph, so clients can render and gate the workflow."""
    initial_state: str
    states: list[WorkflowState] = []


class TransitionRoleUpdate(BaseModel):
    state: str
    transition: str
    roles: list[str] = Field(..., min_length=1)


class TransitionRolesUpdate(BaseModel):
    """Admin redefinition of who may perform each transition. The provided set
    replaces all existing overrides."""
    overrides: list[TransitionRoleUpdate] = []


# --- Release status summary ------------------------------------------------
class RequiredDoc(BaseModel):
    label: str
    present: bool


class ReleaseStatusSummary(BaseModel):
    """Aggregated readiness view for a single release."""
    release_id: int
    state: str
    open_bug_count: int = 0
    open_bugs: list[JiraIssue] = []
    required_docs: list[RequiredDoc] = []
    missing_docs: list[str] = []
    pending_checks: int = 0
    total_checks: int = 0
    is_ready: bool = False


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
