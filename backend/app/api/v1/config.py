"""/api/v1/config — runtime configuration (issue tracker + credentials) and
the global default-check templates. Read is open; writes are admin-only.

Secrets are write-only: tokens are accepted on update but never returned. The
response exposes only whether a token is currently stored (``token_set``).
"""
from __future__ import annotations

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.jwt_verify import ALL_ROLES, ROLE_ADMIN, ROLE_RELEASE_MANAGER, require_role
from app.db.pool import get_conn
from app.schemas.models import (
    CheckTemplate,
    CheckTemplateCreate,
    ClaudeConfigView,
    ConfigUpdate,
    ConfigView,
    GitHubConfigView,
    JiraConfigView,
    LLMConfigView,
    OllamaConfigView,
    TransitionRolesUpdate,
)
from app.repositories import config as repo
from app.services import appconfig
from app.services.state_machine import StateMachine

router = APIRouter()


def get_state_machine(request: Request) -> StateMachine:
    return request.app.state.state_machine


# --- Configuration ---------------------------------------------------------
@router.get("", response_model=ConfigView)
def get_config(conn: psycopg.Connection = Depends(get_conn)):
    cfg = appconfig.effective(conn)
    return ConfigView(
        tracker_provider=cfg.provider,
        jira=JiraConfigView(
            enabled=cfg.jira.enabled,
            base_url=cfg.jira.base_url,
            token_set=bool(cfg.jira.token),
        ),
        github=GitHubConfigView(
            enabled=cfg.github.enabled,
            base_url=cfg.github.base_url,
            token_set=bool(cfg.github.token),
        ),
        llm=LLMConfigView(
            provider=cfg.llm.provider,
            claude=ClaudeConfigView(
                model=cfg.llm.claude_model,
                api_key_set=bool(cfg.llm.claude_api_key),
            ),
            ollama=OllamaConfigView(
                base_url=cfg.llm.ollama_base_url,
                model=cfg.llm.ollama_model,
            ),
        ),
    )


@router.put("", response_model=ConfigView,
            dependencies=[Depends(require_role(ROLE_ADMIN))])
def update_config(body: ConfigUpdate, conn: psycopg.Connection = Depends(get_conn)):
    # Non-exclusive fields: token fields are only persisted when a non-empty
    # value is supplied, so an omitted/blank token keeps the existing secret.
    values: dict[str, str] = {}
    if body.jira_base_url is not None:
        values[appconfig.JIRA_BASE_URL] = body.jira_base_url
    if body.jira_token:
        values[appconfig.JIRA_TOKEN] = body.jira_token
    if body.github_base_url is not None:
        values[appconfig.GITHUB_BASE_URL] = body.github_base_url
    if body.github_token:
        values[appconfig.GITHUB_TOKEN] = body.github_token

    # LLM engine (claude_api_key is write-only: persisted only when non-empty).
    if body.llm_provider is not None:
        values[appconfig.LLM_PROVIDER] = body.llm_provider
    if body.claude_model is not None:
        values[appconfig.CLAUDE_MODEL] = body.claude_model
    if body.claude_api_key:
        values[appconfig.CLAUDE_API_KEY] = body.claude_api_key
    if body.ollama_base_url is not None:
        values[appconfig.OLLAMA_BASE_URL] = body.ollama_base_url
    if body.ollama_model is not None:
        values[appconfig.OLLAMA_MODEL] = body.ollama_model

    # Only one tracker may be enabled at a time. Resolve the requested change
    # against the current state: the tracker just turned on wins and becomes the
    # active provider, forcing the other off. This is enforced here (not just in
    # the UI) so the invariant always holds.
    cur = appconfig.effective(conn)
    jira_en, gh_en, provider = cur.jira.enabled, cur.github.enabled, cur.provider
    if body.jira_enabled is not None:
        jira_en = body.jira_enabled
    if body.github_enabled is not None:
        gh_en = body.github_enabled
    if body.tracker_provider is not None:
        provider = body.tracker_provider

    if body.github_enabled:        # explicitly enabling GitHub
        jira_en, provider = False, "github"
    elif body.jira_enabled:        # explicitly enabling Jira
        gh_en, provider = False, "jira"
    elif jira_en and gh_en:        # both on (shouldn't happen) → provider wins
        jira_en, gh_en = (provider == "jira"), (provider == "github")

    # Keep the active provider pointing at the enabled tracker, if any.
    if jira_en and not gh_en:
        provider = "jira"
    elif gh_en and not jira_en:
        provider = "github"

    values[appconfig.JIRA_ENABLED] = str(jira_en).lower()
    values[appconfig.GITHUB_ENABLED] = str(gh_en).lower()
    values[appconfig.TRACKER_PROVIDER] = provider

    repo.set_many(conn, values)
    return get_config(conn)


# --- Workflow transition roles (admin-defined) -----------------------------
@router.put("/transition-roles", status_code=204,
            dependencies=[Depends(require_role(ROLE_ADMIN))])
def set_transition_roles(
    body: TransitionRolesUpdate,
    conn: psycopg.Connection = Depends(get_conn),
    sm: StateMachine = Depends(get_state_machine),
):
    """Redefine which roles may perform each transition. The supplied set
    replaces all existing overrides. Each entry is validated against the state
    graph and the known roles."""
    overrides: dict[str, list[str]] = {}
    for o in body.overrides:
        if not sm.exists(o.state) or sm.transition(o.state, o.transition) is None:
            raise HTTPException(
                400, f"Unknown transition '{o.transition}' from state '{o.state}'"
            )
        unknown = set(o.roles) - ALL_ROLES
        if unknown:
            raise HTTPException(400, f"Unknown role(s): {', '.join(sorted(unknown))}")
        overrides[appconfig.trans_key(o.state, o.transition)] = sorted(set(o.roles))

    appconfig.set_transition_role_overrides(conn, overrides)


# --- Default check templates -----------------------------------------------
@router.get("/check-templates", response_model=list[CheckTemplate])
def list_check_templates(conn: psycopg.Connection = Depends(get_conn)):
    return repo.list_check_templates(conn)


@router.post("/check-templates", response_model=CheckTemplate, status_code=201,
             dependencies=[Depends(require_role(ROLE_RELEASE_MANAGER, ROLE_ADMIN))])
def add_check_template(body: CheckTemplateCreate, conn: psycopg.Connection = Depends(get_conn)):
    return repo.add_check_template(conn, body.label, body.phase)


@router.delete("/check-templates/{template_id}", status_code=204,
               dependencies=[Depends(require_role(ROLE_RELEASE_MANAGER, ROLE_ADMIN))])
def delete_check_template(template_id: int, conn: psycopg.Connection = Depends(get_conn)):
    if not repo.delete_check_template(conn, template_id):
        raise HTTPException(404, "Check template not found")
