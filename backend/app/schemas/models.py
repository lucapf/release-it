"""Pydantic request/response models. Rows from psycopg (dict_row) map directly."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


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
    note: str = Field("", description="Optional free-text comment explaining the state change")


class InheritRequest(BaseModel):
    version: str = Field(..., description="Version for the new inherited release")


# --- Artifact / Documentation (metadata only; content streamed separately) -
class ArtifactMeta(BaseModel):
    id: int
    release_id: int
    name: str
    content_type: str
    created_at: datetime


# --- Document management (versioned, release-scoped) -----------------------
# Supported document types are admin-managed (see config endpoints / the
# `document_type` table), not a fixed code-level set. An operator marks each
# document with one of the configured type names; uploads are validated against
# the configured set.
class DocumentTypeCreate(BaseModel):
    name: str
    # 'manual' documents are uploaded by an operator; 'generated' ones are built
    # by the system from ``generation_prompt``.
    kind: Literal["manual", "generated"] = "manual"
    generation_prompt: str = ""


class DocumentTypeUpdate(BaseModel):
    """Editable document-type fields. Only the supplied fields change."""
    name: str | None = None
    kind: Literal["manual", "generated"] | None = None
    generation_prompt: str | None = None


class DocumentType(BaseModel):
    id: int
    name: str
    kind: str = "manual"
    generation_prompt: str = ""
    created_at: datetime


class DocumentVersionMeta(BaseModel):
    """One uploaded version of a document (content streamed separately)."""
    id: int
    document_id: int
    version: int
    filename: str
    content_type: str
    size: int
    pdf_size: int = 0  # bytes of the rendered-PDF companion (0 when there is none)
    uploaded_by: str | None = None
    created_at: datetime


class DocumentMeta(BaseModel):
    """A logical document plus the metadata of its latest version."""
    id: int
    release_id: int
    title: str
    doc_type: str
    status: str = "DRAFT"  # DRAFT until an operator approves it
    created_at: datetime
    version_count: int = 0
    latest_version_id: int | None = None
    latest_version: int | None = None
    latest_filename: str | None = None
    latest_content_type: str | None = None
    latest_size: int | None = None
    latest_pdf_size: int | None = None  # >0 when a downloadable PDF companion exists
    latest_uploaded_by: str | None = None
    updated_at: datetime | None = None


class DocumentStatusUpdate(BaseModel):
    """Approve (or return to draft) a document."""
    status: Literal["DRAFT", "APPROVED"]


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
    # The issue's page in the tracker's web UI. Empty for issues cached before
    # the URL was recorded — they get one on the next sync.
    url: str = ""
    synced_at: datetime


class IssueDetail(BaseModel):
    """One issue fetched live from the tracker, for the on-demand detail view.
    Fields a given tracker does not carry come back empty (GitHub has no
    priority; an unassigned issue has no assignee)."""
    key: str
    type: str
    summary: str
    status: str
    url: str = ""
    description: str = ""
    assignee: str = ""
    reporter: str = ""
    priority: str = ""
    labels: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


class SyncFilter(BaseModel):
    """The tracker filter an operator chose for a release, persisted so it can
    be re-applied automatically. ``mode`` is one of ``milestone | label | jql``.
    """
    mode: str = Field(description="milestone | label | jql")
    value: str = Field(default="", description="The filter value for the chosen mode")


class SyncFilterView(SyncFilter):
    release_id: int
    updated_at: datetime


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
    # Scheduled issue sync interval, in minutes (0 = disabled). Default: 10.
    sync_interval_minutes: int = 10
    jira: JiraConfigView = JiraConfigView()
    github: GitHubConfigView = GitHubConfigView()
    llm: LLMConfigView = LLMConfigView()


class ConfigUpdate(BaseModel):
    """Configuration update. A token/key left as None/empty is kept unchanged,
    so secrets are write-only — they are never echoed back by the API."""
    tracker_provider: Literal["jira", "github"] | None = None
    sync_interval_minutes: int | None = Field(
        default=None, ge=0, description="Scheduled issue sync interval in minutes (0 disables)"
    )
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


# --- Workflow (state machine exposure) -------------------------------------
class WorkflowTransition(BaseModel):
    name: str
    target: str
    roles: list[str] = []  # roles permitted to perform this transition
    requires: list[str] = []  # readiness guards (e.g. no_open_issues, document:<type>)


class WorkflowState(BaseModel):
    name: str
    score: int
    is_final: bool
    transitions: list[WorkflowTransition] = []


class Workflow(BaseModel):
    """The release state graph, so clients can render and gate the workflow."""
    initial_state: str
    states: list[WorkflowState] = []


class WorkflowTransitionInput(BaseModel):
    name: str
    target: str
    roles: list[str] = []
    requires: list[str] = []


class WorkflowStateInput(BaseModel):
    name: str
    transitions: list[WorkflowTransitionInput] = []


class WorkflowUpdate(BaseModel):
    """A complete replacement of the release workflow graph. The order of
    ``states`` defines their scoring, so the first state is the initial one."""
    states: list[WorkflowStateInput] = Field(..., min_length=1)


class TransitionRoleUpdate(BaseModel):
    state: str
    transition: str
    roles: list[str] = Field(..., min_length=1)


class TransitionRolesUpdate(BaseModel):
    """Admin redefinition of who may perform each transition. The provided set
    replaces all existing overrides."""
    overrides: list[TransitionRoleUpdate] = []


# --- Release status summary ------------------------------------------------
class ReleaseStatusSummary(BaseModel):
    """Aggregated readiness view for a single release."""
    release_id: int
    state: str
    open_bug_count: int = 0
    open_bugs: list[JiraIssue] = []
    # Document types currently uploaded on the release — feeds `document:<type>`
    # workflow readiness guards.
    present_doc_types: list[str] = []
    is_ready: bool = False


class ReleaseBugCount(BaseModel):
    """Total bugs in a release, counted live from the active tracker by the
    release label ``v<major>.<minor>.<patch>`` (e.g. ``v0.0.1``)."""
    release_id: int
    label: str
    total_bugs: int


# --- LLM assistant (chat) --------------------------------------------------
class ChatMessage(BaseModel):
    """One turn of the operator/assistant conversation. The client sends the full
    transcript each request; the server is stateless between calls."""
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., min_length=1)


class ChatAction(BaseModel):
    """A tool the assistant invoked while answering — surfaced so the operator can
    see what was read or changed on their behalf."""
    tool: str
    ok: bool
    summary: str


class ChatDocumentRef(BaseModel):
    """A document the assistant surfaced for the operator to download — the chat
    UI renders authenticated Markdown/PDF download buttons from it."""
    release_id: int
    document_id: int
    version_id: int | None = None
    title: str
    doc_type: str
    status: str
    filename: str
    has_pdf: bool = False


class ChatResponse(BaseModel):
    reply: str
    actions: list[ChatAction] = []
    documents: list[ChatDocumentRef] = []


class AssistantAction(BaseModel):
    """One capability of the assistant, described from its live tool registry.
    ``kind`` is "read" for inspection tools and "action" for tools that change
    the system."""
    name: str
    kind: Literal["read", "action"]
    description: str


class AssistantPrompt(BaseModel):
    """A ready-to-use prompt template for a common assistant task."""
    key: str
    title: str
    description: str
    prompt: str


class AssistantCapabilities(BaseModel):
    actions: list[AssistantAction] = []
    prompts: list[AssistantPrompt] = []


class AssistantPromptUpdate(BaseModel):
    """One prompt in an admin's edit. ``key`` selects a built-in template; the
    text fields carry the desired content. A field equal to the built-in default
    (or blank) stores no override, so the prompt keeps tracking the default."""
    key: str
    title: str | None = None
    description: str | None = None
    prompt: str | None = None


class AssistantPromptsUpdate(BaseModel):
    """Full desired state of the editable prompts. Prompts omitted here are reset
    to their built-in defaults."""
    prompts: list[AssistantPromptUpdate] = []


# --- Audit -----------------------------------------------------------------
class AuditEntry(BaseModel):
    id: int
    entity_type: str
    entity_id: int
    action: str
    old_value: str | None
    new_value: str | None
    operator: str | None
    note: str | None = None
    created_at: datetime
