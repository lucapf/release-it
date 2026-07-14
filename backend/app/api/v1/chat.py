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
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from app.core.config import settings
from app.core.identity import Principal, current_principal
from app.db.pool import get_conn
from app.integrations.llm_chat import SYSTEM_PROMPT, get_chat_service
from app.repositories import chat_attachments as attachments_repo
from app.schemas.models import (
    AssistantCapabilities,
    ChatAction,
    ChatAttachment,
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


@router.post("/attachments", response_model=ChatAttachment, status_code=201)
async def upload_attachment(
    file: UploadFile = File(...),
    conn: psycopg.Connection = Depends(get_conn),
    principal: Principal = Depends(current_principal),
):
    """Stage a file the operator attached in the chat.

    The chat transcript carries text only, so the bytes cannot ride along in it.
    They are held here instead and the assistant is shown only the metadata this
    returns; it works out which release/document the file belongs to, confirms
    with the operator, and links it with the ``attachment_id``. Nothing is
    attached to a release until that happens — an attachment the operator never
    links is purged after ``chat_attachments.TTL_HOURS``.
    """
    content = await file.read()
    limit = settings.max_document_size_mb * 1024 * 1024
    if len(content) > limit:
        raise HTTPException(
            413,
            f"The file exceeds the maximum allowed size of {settings.max_document_size_mb} MB",
        )
    if not content:
        raise HTTPException(400, "The file is empty")
    attachments_repo.purge_stale(conn)
    row = attachments_repo.create(
        conn,
        file.filename or "attachment",
        file.content_type or "application/octet-stream",
        content,
        principal.subject or None,
    )
    return ChatAttachment(**{k: row[k] for k in ("id", "filename", "content_type", "size")})


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

    # Any files the operator has attached and not yet linked. The client resends
    # their ids every turn; we only surface the ones it actually uploaded and has
    # not spent, so a stale or borrowed id shows the model nothing.
    pending = attachments_repo.pending(conn, body.attachment_ids, principal.subject or None)
    attachment_context = assistant.render_attachment_context(conn, pending)
    if attachment_context:
        system = f"{system}\n\n{attachment_context}"

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
        # Read back from the staging table rather than from the tool results: it is
        # the table that decides whether an attachment was really spent, so the UI
        # can never keep resending a file that has already become a document.
        linked_attachment_ids=attachments_repo.linked_ids(conn, body.attachment_ids),
    )
