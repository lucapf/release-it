"""/api/v1/chat — the LLM-driven operator assistant.

A single stateless endpoint: the client posts the whole conversation so far, the
model runs an agentic tool-use loop (reading the database and, when asked,
creating releases, uploading documents, transitioning, syncing issues), and we
return its reply plus the list of tool actions it performed.

The model acts on behalf of the authenticated operator (gateway-injected
identity), so every action goes through the same role/readiness enforcement as
the REST API — see :mod:`app.services.assistant`.
"""
from __future__ import annotations

import logging

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.identity import Principal, current_principal
from app.db.pool import get_conn
from app.integrations.llm_chat import SYSTEM_PROMPT, get_chat_service
from app.schemas.models import (
    AssistantCapabilities,
    ChatAction,
    ChatDocumentRef,
    ChatRequest,
    ChatResponse,
)
from app.services import appconfig, assistant

log = logging.getLogger("releaseit.chat")

router = APIRouter()


@router.get("/capabilities", response_model=AssistantCapabilities)
def capabilities(conn: psycopg.Connection = Depends(get_conn)):
    """What the assistant can do: its actions (described from the live tool
    registry) and the ready-to-use prompt templates for its main jobs. The
    actions are static; the prompts reflect any admin edits (see PUT
    /config/prompts). No model call is made."""
    return AssistantCapabilities(
        actions=assistant.describe_actions(),
        prompts=assistant.effective_prompts(appconfig.prompt_overrides(conn)),
    )


@router.post("", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    request: Request,
    conn: psycopg.Connection = Depends(get_conn),
    principal: Principal = Depends(current_principal),
):
    """Answer the operator's message, using tools to read/act on the system."""
    if body.messages[-1].role != "user":
        raise HTTPException(400, "The last message must be from the operator")

    cfg = appconfig.effective(conn)
    try:
        service = get_chat_service(cfg.llm)
    except RuntimeError as exc:
        # No engine configured — a clear, actionable error for the operator.
        raise HTTPException(400, str(exc)) from exc

    ctx = assistant.ToolContext(
        conn=conn,
        principal=principal,
        sm=request.app.state.state_machine,
        cfg=cfg,
    )
    dispatch, tools = assistant.make_dispatcher(ctx)
    history = [{"role": m.role, "content": m.content} for m in body.messages]

    # Append the predefined jobs (with any admin overrides) to the system prompt so
    # the assistant can match an operator's request to a job, announce it, and run
    # it — see assistant.render_job_playbook.
    prompts = assistant.effective_prompts(appconfig.prompt_overrides(conn))
    system = f"{SYSTEM_PROMPT}\n\n{assistant.render_job_playbook(prompts)}"

    try:
        result = service.run(
            system=system, history=history, tools=tools, dispatch=dispatch
        )
    except Exception as exc:  # engine/transport failures (e.g. Anthropic API down)
        # Log the full stacktrace server-side — the client only gets a short
        # summary, so without this the actual cause never reaches the logs.
        log.exception("assistant engine failed for provider %s", cfg.llm.provider)
        raise HTTPException(502, f"The assistant engine failed: {exc}") from exc

    # Collect the documents the assistant surfaced (most recent last wins per
    # document) so the UI can render authenticated download buttons for them.
    documents: dict[int, ChatDocumentRef] = {}
    for a in result.actions:
        if a.ok and a.document:
            ref = ChatDocumentRef(**a.document)
            documents[ref.document_id] = ref

    return ChatResponse(
        reply=result.reply,
        actions=[ChatAction(tool=a.tool, ok=a.ok, summary=a.summary) for a in result.actions],
        documents=list(documents.values()),
    )
