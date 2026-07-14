"""The assistant's toolbox — how the LLM reads the database and performs actions.

Each tool is a thin, JSON-schema-described wrapper over the same repositories and
services the REST API uses, so the assistant is subject to the exact same role
checks, readiness guards and audit logging as the UI. Write tools reuse
:mod:`app.services.release_ops`; readiness is computed by
:mod:`app.services.release_status`.

The dispatcher runs every tool inside its own SAVEPOINT: a tool that fails (bad
input, a guard rejection, a DB error) rolls back only its own effects and returns
an error to the model, leaving the connection usable for the next tool and any
successful writes intact.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx
import psycopg

from app.core.identity import Principal
from app.integrations import trackers
from app.integrations.git import GitNotConfigured, GitUnreachable
from app.integrations.llm_chat import ActionRecord, Dispatch, ToolSpec
from app.repositories import chat_attachments as chat_attachments_repo
from app.repositories import config as config_repo
from app.repositories import documents as documents_repo
from app.repositories import products as products_repo
from app.repositories import releases as releases_repo
from app.services import appconfig, audit, code_review, doc_render, git_changes, release_ops
from app.services import issues as issues_svc
from app.services.release_status import compute_status, unmet_requirements
from app.services.state_machine import StateMachine

log = logging.getLogger("releaseit.assistant")

# How many recent audit entries to include per release in status reports.
_HISTORY_LIMIT = 15


@dataclass
class ToolContext:
    """Everything a tool needs to touch the system on the operator's behalf."""
    conn: psycopg.Connection
    principal: Principal
    sm: StateMachine
    cfg: appconfig.EffectiveConfig


# --- Compact serialisers (keep tool payloads small and stable) --------------
def _release_brief(rel: dict) -> dict:
    return {
        "id": rel["id"],
        "product_id": rel["product_id"],
        "version": rel["version"],
        "state": rel["state"],
        "short_description": rel.get("short_description", ""),
    }


def _issue_brief(issue: dict) -> dict:
    """One ticket as reported to the model — from the tracker's live answer, so
    `closed` is the tracker's current verdict and not a remembered one."""
    return {
        "key": issue["key"],
        "type": issue["type"],
        "summary": issue["summary"],
        "status": issue["status"],
        "closed": bool(issue.get("closed")),
    }


def _audit_brief(entry: dict) -> dict:
    return {
        "action": entry["action"],
        "from": entry["old_value"],
        "to": entry["new_value"],
        "operator": entry["operator"],
        "note": entry.get("note"),
        "at": str(entry["created_at"]),
    }


def _require_release(ctx: ToolContext, release_id: Any) -> dict:
    rel = releases_repo.get(ctx.conn, int(release_id))
    if rel is None:
        raise release_ops.ReleaseActionError(404, f"Release {release_id} not found")
    return rel


def _document_brief(doc: dict) -> dict:
    """A document row (from list_documents/get_document_meta) as reported to the
    model: identity, type, approval status and downloadable formats."""
    return {
        "id": doc["id"],
        "title": doc["title"],
        "doc_type": doc["doc_type"],
        "status": doc.get("status", "DRAFT"),
        "latest_version": doc.get("latest_version"),
        "version_count": doc.get("version_count"),
        "formats": ["markdown"] + (["pdf"] if (doc.get("latest_pdf_size") or 0) > 0 else []),
    }


def _document_ref(release_id: int, doc: dict) -> dict:
    """The download reference the chat UI turns into authenticated md/pdf buttons.
    Shape matches :class:`app.schemas.models.ChatDocumentRef`."""
    return {
        "release_id": release_id,
        "document_id": doc["id"],
        "version_id": doc.get("latest_version_id"),
        "title": doc["title"],
        "doc_type": doc["doc_type"],
        "status": doc.get("status", "DRAFT"),
        "filename": doc.get("latest_filename") or f'{doc["title"]}.md',
        "has_pdf": (doc.get("latest_pdf_size") or 0) > 0,
    }


def _resolve_document(ctx: ToolContext, rel: dict, args: dict) -> dict:
    """Find the document referenced by ``document_id`` or ``title`` on the release."""
    if args.get("document_id") is not None:
        doc = documents_repo.get_document(ctx.conn, int(args["document_id"]))
        if doc is None or doc["release_id"] != rel["id"]:
            raise release_ops.ReleaseActionError(404, f'Document {args["document_id"]} not found')
        return doc
    title = (args.get("title") or "").strip()
    if title:
        doc = documents_repo.find_document(ctx.conn, rel["id"], title)
        if doc is None:
            raise release_ops.ReleaseActionError(404, f'No document titled "{title}" on this release')
        return doc
    raise release_ops.ReleaseActionError(422, "Provide the document_id or title")


def _blockers(ctx: ToolContext, rel: dict, status) -> list[dict]:
    """For each transition out of the release's current state, the readiness
    requirements that are not yet met (i.e. what is blocking forward progress)."""
    out = []
    for trans in ctx.sm.transitions(rel["state"]):
        unmet = unmet_requirements(trans.requires, status)
        if unmet:
            out.append({"transition": trans.name, "target": trans.target, "blocked_by": unmet})
    return out


def _status_report_for(ctx: ToolContext, rel: dict) -> dict:
    """The full status picture for one release: state, readiness, blockers, the
    actions performed so far, and the transitions available next."""
    status = compute_status(ctx.conn, rel)
    history = audit.list_for(ctx.conn, entity_type="release", entity_id=rel["id"])
    documents = documents_repo.list_documents(ctx.conn, rel["id"])
    return {
        "release_id": rel["id"],
        "product_id": rel["product_id"],
        "version": rel["version"],
        "state": rel["state"],
        "is_ready": status.is_ready,
        "open_issues": [_issue_brief(i.model_dump() if hasattr(i, "model_dump") else i)
                        for i in status.open_bugs],
        "present_document_types": status.present_doc_types,
        "approved_document_types": status.approved_doc_types,
        "documents": [_document_brief(d) for d in documents],
        "blockers": _blockers(ctx, rel, status),
        "actions_performed": [_audit_brief(e) for e in history[:_HISTORY_LIMIT]],
        "available_transitions": [t.name for t in ctx.sm.transitions(rel["state"])],
    }


# --- Read tools ------------------------------------------------------------
def _list_products(ctx: ToolContext, args: dict) -> Any:
    return [
        {"id": p["id"], "name": p["name"], "tracker_repo": p.get("tracker_repo", "")}
        for p in products_repo.list_all(ctx.conn)
    ]


def _resolve_product_id(ctx: ToolContext, args: dict) -> int | None:
    if args.get("product_id") is not None:
        return int(args["product_id"])
    name = (args.get("product_name") or "").strip().lower()
    if name:
        for p in products_repo.list_all(ctx.conn):
            if p["name"].lower() == name:
                return p["id"]
        raise release_ops.ReleaseActionError(404, f'No product named "{args["product_name"]}"')
    return None


def _list_releases(ctx: ToolContext, args: dict) -> Any:
    product_id = _resolve_product_id(ctx, args)
    if product_id is not None:
        rows = releases_repo.list_by_product(ctx.conn, product_id)
    else:
        rows = releases_repo.list_all(ctx.conn)
    return [_release_brief(r) for r in rows]


def _get_release_status(ctx: ToolContext, args: dict) -> Any:
    rel = _require_release(ctx, args["release_id"])
    return _status_report_for(ctx, rel)


def _project_status_report(ctx: ToolContext, args: dict) -> Any:
    """Status of every *running* (non-final) release, optionally scoped to one
    product. This is the report tool for 'list project statuses'."""
    product_id = _resolve_product_id(ctx, args)
    if product_id is not None:
        rows = releases_repo.list_by_product(ctx.conn, product_id)
    else:
        rows = releases_repo.list_all(ctx.conn)

    products = {p["id"]: p["name"] for p in products_repo.list_all(ctx.conn)}
    final_states = {s.name for s in ctx.sm.states() if s.is_final}

    reports = []
    for rel in rows:
        if rel["state"] in final_states:
            continue  # only releases still in flight
        # One tracker query per release, and one product's tracker being
        # unreachable must not sink the whole report. That release is reported as
        # *unknown* rather than dropped or, worse, as having no open issues —
        # "we could not check" and "nothing is blocking it" are different answers.
        try:
            report = _status_report_for(ctx, rel)
        except (trackers.TrackerError, httpx.HTTPError, ValueError) as exc:
            report = {
                "release_id": rel["id"],
                "product_id": rel["product_id"],
                "version": rel["version"],
                "state": rel["state"],
                "issues_unavailable": f"the ticketing system could not be queried: {exc}",
                "is_ready": False,
            }
        report["product_name"] = products.get(rel["product_id"], "")
        reports.append(report)
    return {"running_release_count": len(reports), "releases": reports}


def _list_release_issues(ctx: ToolContext, args: dict) -> Any:
    """The release's tickets, read from the ticketing system now — there is no
    stored list to read instead."""
    rel = _require_release(ctx, args["release_id"])
    return [_issue_brief(i) for i in issues_svc.for_release(ctx.conn, ctx.cfg, rel)]


def _list_documents(ctx: ToolContext, args: dict) -> Any:
    _require_release(ctx, args["release_id"])
    docs = documents_repo.list_documents(ctx.conn, int(args["release_id"]))
    return [_document_brief(d) for d in docs]


def _list_document_types(ctx: ToolContext, args: dict) -> Any:
    """The configured document types, each flagged with how it is produced:
    'automatic' (the assistant can generate it from its prompt) or 'manual' (an
    operator must upload the file)."""
    rows = config_repo.list_document_types(ctx.conn)
    return [
        {
            "name": r["name"],
            "generation": "automatic" if r["kind"] == "generated" else "manual",
        }
        for r in sorted(rows, key=lambda r: r["name"].lower())
    ]


def _get_generation_prompt(ctx: ToolContext, args: dict) -> Any:
    """Gate for generating a document: verify the document type is supported and
    set to automatic generation, and return its configured generation prompt.

    Fails with a clear, operator-facing reason when the type does not exist, is
    set to manual (operator-uploaded), or has no prompt configured — so the model
    can relay exactly why the document cannot be generated instead of inventing one."""
    name = str(args.get("doc_type", "")).strip()
    if not name:
        raise release_ops.ReleaseActionError(422, "Provide the document type to generate")
    dtype = config_repo.get_document_type_by_name(ctx.conn, name)
    if dtype is None:
        supported = sorted(config_repo.document_type_names(ctx.conn))
        raise release_ops.ReleaseActionError(
            404,
            f'Document type "{name}" is not supported by the system. '
            f'Configured types: {", ".join(supported) or "none"}.',
        )
    if dtype["kind"] != "generated":
        raise release_ops.ReleaseActionError(
            400,
            f'Document type "{dtype["name"]}" is set to manual generation; it must be '
            "uploaded by an operator and cannot be generated by the assistant.",
        )
    prompt = (dtype["generation_prompt"] or "").strip()
    if not prompt:
        raise release_ops.ReleaseActionError(
            400,
            f'Document type "{dtype["name"]}" is set to automatic generation but has no '
            "generation prompt configured; an administrator must add one.",
        )
    return {
        "doc_type": dtype["name"],
        "generation": "automatic",
        "generation_prompt": prompt,
    }


# --- Action tools ----------------------------------------------------------
def _create_release(ctx: ToolContext, args: dict) -> Any:
    rel = release_ops.create_release(
        ctx.conn, ctx.sm, ctx.principal,
        product_id=int(args["product_id"]),
        version=str(args["version"]).strip(),
        short_description=str(args.get("short_description", "") or ""),
        filter_mode=str(args.get("criteria_mode", "") or ""),
        filter_value=str(args.get("criteria_value", "") or ""),
    )
    brief = _release_brief(rel)
    brief["issues"] = [_issue_brief(i) for i in issues_svc.for_release(ctx.conn, ctx.cfg, rel)]
    return brief


def _get_issue(ctx: ToolContext, args: dict) -> Any:
    """One ticket in full, for an operator asking about a specific one: its key,
    summary, description, status and the link to open it in the ticketing system."""
    rel = _require_release(ctx, args["release_id"])
    issue = issues_svc.detail(ctx.conn, ctx.cfg, rel, str(args["key"]))
    return {
        "key": issue["key"],
        "summary": issue["summary"],
        "description": issue["description"],
        "status": issue["status"],
        "closed": issue["closed"],
        # The operator's way to the ticket itself for anything this does not carry.
        "url": issue["url"],
        "type": issue["type"],
        "assignee": issue["assignee"],
        "priority": issue["priority"],
        "labels": issue["labels"],
    }


def _set_membership(ctx: ToolContext, args: dict, *, member: bool) -> Any:
    """Add/remove a ticket by editing it until it matches (or stops matching) the
    release's criteria — see :func:`app.services.issues.set_membership`."""
    rel = _require_release(ctx, args["release_id"])
    result = issues_svc.set_membership(
        ctx.conn, ctx.cfg, rel, str(args["key"]), member=member
    )
    audit.record(ctx.conn, entity_type="release", entity_id=rel["id"],
                 action="issue_added" if member else "issue_removed",
                 operator=ctx.principal.subject,
                 new_value=f'{result["key"]} ({result["criteria"]})')
    return {
        "key": result["key"],
        "in_release": result["member"],
        # What was actually done to the ticket, so the model reports the edit and
        # not just "done" — the operator's ticket was changed in their tracker.
        "edit": (f'{"added" if member else "removed"} to satisfy the release criteria '
                 f'{result["criteria"]}'),
        "release_now_contains": result["total"],
        "issues": [_issue_brief(i) for i in result["issues"]],
    }


def _add_issue_to_release(ctx: ToolContext, args: dict) -> Any:
    return _set_membership(ctx, args, member=True)


def _remove_issue_from_release(ctx: ToolContext, args: dict) -> Any:
    return _set_membership(ctx, args, member=False)


def _search_issues(ctx: ToolContext, args: dict) -> Any:
    """Preview a criteria against the tracker before it is bound to a release —
    the tickets it would select, so the operator can confirm they are the right
    ones (the UI shows the same list when a release is created)."""
    query, issues = issues_svc.search(
        ctx.conn, ctx.cfg, int(args["product_id"]),
        str(args.get("criteria_mode", "") or ""),
        str(args.get("criteria_value", "") or ""),
    )
    return {"query": query, "total": len(issues),
            "issues": [_issue_brief(i) for i in issues]}


def _set_release_criteria(ctx: ToolContext, args: dict) -> Any:
    """Change which tickets a release contains, by changing its search criteria.

    This is the only writable thing about a release's issues: the tickets
    themselves live in the ticketing system and are never written from here.
    """
    rel = _require_release(ctx, args["release_id"])
    try:
        mode, value = issues_svc.validate_criteria(
            ctx.cfg,
            str(args.get("criteria_mode", "") or ""),
            str(args.get("criteria_value", "") or ""),
        )
    except issues_svc.IssueCriteriaError as exc:
        raise release_ops.ReleaseActionError(422, str(exc)) from exc

    previous = issues_svc.get_criteria(ctx.conn, rel["id"])
    issues_svc.save_criteria(ctx.conn, rel["id"], mode, value)
    audit.record(ctx.conn, entity_type="release", entity_id=rel["id"],
                 action="issue_criteria", operator=ctx.principal.subject,
                 old_value=(f'{previous["filter_mode"]} = {previous["filter_value"]}'
                            if previous else None),
                 new_value=f"{mode} = {value}")
    issues = issues_svc.for_release(ctx.conn, ctx.cfg, rel)
    return {"criteria": f"{mode} = {value}", "total": len(issues),
            "issues": [_issue_brief(i) for i in issues]}


def _upload_document(ctx: ToolContext, args: dict) -> Any:
    rel = _require_release(ctx, args["release_id"])
    doc_type = str(args["doc_type"]).strip()
    if doc_type not in config_repo.document_type_names(ctx.conn):
        raise release_ops.ReleaseActionError(400, f'Unsupported document type "{doc_type}"')
    title = str(args["title"]).strip()
    if not title:
        raise release_ops.ReleaseActionError(422, "A document title is required")
    if documents_repo.find_document(ctx.conn, rel["id"], title) is not None:
        raise release_ops.ReleaseActionError(
            409, f'A document titled "{title}" already exists on this release'
        )
    content = str(args["content"]).encode("utf-8")
    filename = (args.get("filename") or f"{title}.md").strip()
    doc = documents_repo.create_document(ctx.conn, rel["id"], title, doc_type)
    # Assistant-authored documents are Markdown; render the PDF companion and land
    # them as DRAFT (repo.add_version), awaiting an operator's approval.
    pdf = doc_render.pdf_for(doc_render.MARKDOWN_CONTENT_TYPE, content, filename=filename, title=title)
    documents_repo.add_version(
        ctx.conn, doc["id"], filename, doc_render.MARKDOWN_CONTENT_TYPE, content,
        ctx.principal.subject or None, pdf,
    )
    meta = documents_repo.get_document_meta(ctx.conn, doc["id"])
    return {
        "id": meta["id"],
        "title": meta["title"],
        "doc_type": meta["doc_type"],
        "status": meta["status"],
        "latest_version": meta["latest_version"],
        "bytes": len(content),
        "formats": _document_brief(meta)["formats"],
        "document_ref": _document_ref(rel["id"], meta),
    }


# --- Operator-attached files ------------------------------------------------
# A file the operator attaches in the chat is staged in `chat_attachment` and the
# model only ever sees its metadata (see the chat endpoint). These two tools are
# how the staged bytes become a document: as a brand-new document, or as the next
# version of one that already exists. Both spend the attachment, so a file cannot
# be linked twice.
def _require_attachment(ctx: ToolContext, attachment_id: Any) -> tuple[dict, bytes]:
    """The staged file, if it exists, belongs to this operator and is unspent."""
    meta = chat_attachments_repo.get(ctx.conn, int(attachment_id))
    if meta is None:
        raise release_ops.ReleaseActionError(
            404, f"No attached file {attachment_id} — ask the operator to attach it again"
        )
    if meta["uploaded_by"] != (ctx.principal.subject or None):
        raise release_ops.ReleaseActionError(
            403, f"Attachment {attachment_id} was not uploaded by this operator"
        )
    if meta["linked_at"] is not None:
        raise release_ops.ReleaseActionError(
            409,
            f'The attached file "{meta["filename"]}" has already been linked to '
            f'document {meta["linked_document_id"]}',
        )
    content = chat_attachments_repo.content_of(ctx.conn, meta["id"])
    if content is None:
        raise release_ops.ReleaseActionError(404, f"Attached file {attachment_id} is gone")
    return meta, content


def _store_attachment_version(
    ctx: ToolContext, rel: dict, doc: dict, meta: dict, content: bytes
) -> dict:
    """Copy a staged file into a new version of ``doc`` and spend the attachment.

    The version lands as DRAFT (add_version always returns a document to DRAFT) —
    the assistant asks the operator afterwards whether to approve it."""
    if chat_attachments_repo.mark_linked(ctx.conn, meta["id"], doc["id"]) is None:
        # Lost a race with a concurrent link: the row was spent between the check
        # in _require_attachment and here. Fail rather than store a second copy.
        raise release_ops.ReleaseActionError(
            409, f'The attached file "{meta["filename"]}" has already been linked'
        )
    version = documents_repo.add_version(
        ctx.conn,
        doc["id"],
        meta["filename"],
        meta["content_type"],
        content,
        ctx.principal.subject or None,
        doc_render.pdf_for(
            meta["content_type"], content, filename=meta["filename"], title=doc["title"]
        ),
    )
    doc_meta = documents_repo.get_document_meta(ctx.conn, doc["id"])
    brief = _document_brief(doc_meta)
    brief.update(
        {
            "attachment_id": meta["id"],
            "filename": meta["filename"],
            "bytes": len(content),
            "version": version["version"],
            "document_ref": _document_ref(rel["id"], doc_meta),
        }
    )
    return brief


def _link_attachment_as_new_document(ctx: ToolContext, args: dict) -> Any:
    """Attach the operator's uploaded file to a release as a NEW document."""
    rel = _require_release(ctx, args["release_id"])
    meta, content = _require_attachment(ctx, args["attachment_id"])
    doc_type = str(args["doc_type"]).strip()
    if doc_type not in config_repo.document_type_names(ctx.conn):
        raise release_ops.ReleaseActionError(400, f'Unsupported document type "{doc_type}"')
    title = str(args.get("title") or meta["filename"]).strip() or meta["filename"]
    existing = documents_repo.find_document(ctx.conn, rel["id"], title)
    if existing is not None:
        raise release_ops.ReleaseActionError(
            409,
            f'A document titled "{title}" already exists on this release — link the '
            f"file as a new version of it (document_id {existing['id']}) instead",
        )
    doc = documents_repo.create_document(ctx.conn, rel["id"], title, doc_type)
    return _store_attachment_version(ctx, rel, {**doc, "title": title}, meta, content)


def _link_attachment_as_new_version(ctx: ToolContext, args: dict) -> Any:
    """Attach the operator's uploaded file as the next version of an EXISTING
    document (the previous versions stay downloadable)."""
    rel = _require_release(ctx, args["release_id"])
    meta, content = _require_attachment(ctx, args["attachment_id"])
    doc = _resolve_document(ctx, rel, args)
    return _store_attachment_version(ctx, rel, doc, meta, content)


def _transition_release(ctx: ToolContext, args: dict) -> Any:
    rel = release_ops.apply_transition(
        ctx.conn, ctx.sm, ctx.principal,
        int(args["release_id"]), str(args["transition"]).strip(),
        note=str(args.get("note", "") or "").strip(),
    )
    return _release_brief(rel)


def _approve_document(ctx: ToolContext, args: dict) -> Any:
    """Mark a document as APPROVED (operator sign-off on a draft)."""
    rel = _require_release(ctx, args["release_id"])
    doc = _resolve_document(ctx, rel, args)
    meta = documents_repo.set_status(ctx.conn, doc["id"], "APPROVED")
    return {
        "id": meta["id"],
        "title": meta["title"],
        "status": meta["status"],
        "document_ref": _document_ref(rel["id"], meta),
    }


def _get_document(ctx: ToolContext, args: dict) -> Any:
    """Surface a document for download — returns its metadata plus a reference the
    chat UI renders as authenticated Markdown/PDF download buttons."""
    rel = _require_release(ctx, args["release_id"])
    doc = _resolve_document(ctx, rel, args)
    meta = documents_repo.get_document_meta(ctx.conn, doc["id"])
    brief = _document_brief(meta)
    brief["document_ref"] = _document_ref(rel["id"], meta)
    return brief


# --- Code changes (read live from the git hosting) ---------------------------
# Bounds for change payloads returned to the model: tool results are fed to it
# verbatim, so a component's full commit list must never ride along unasked.
_COMMIT_LIMIT = 50
_SUBJECT_LIMIT = 120
_UNMAPPED_SAMPLE = 10


def _changes_for(ctx: ToolContext, rel: dict) -> git_changes.ReleaseChangeSet:
    """The release's change-set, with hosting failures translated into errors
    the model can relay verbatim — never into an empty change-set."""
    try:
        return git_changes.compute_release_changes(ctx.conn, ctx.cfg, rel)
    except git_changes.ChangesUnavailable as exc:
        raise release_ops.ReleaseActionError(400, str(exc)) from exc
    except GitNotConfigured as exc:
        raise release_ops.ReleaseActionError(
            503, f"The git hosting cannot be queried: {exc}"
        ) from exc
    except GitUnreachable as exc:
        raise release_ops.ReleaseActionError(
            502, f"Git hosting query failed: {exc}"
        ) from exc


def _component_summary(c: git_changes.ComponentChange) -> dict:
    return {
        "name": c.name,
        "repo": c.repo,
        "old_version": c.old_version,
        "new_version": c.new_version,
        "status": c.status,
        "error": c.error,
        "commit_count": c.commit_count,
        "mapped_commits": c.mapped_count,
        "unmapped_commits": c.unmapped_count,
        "compare_url": c.compare_url,
    }


def _get_release_changes(ctx: ToolContext, args: dict) -> Any:
    rel = _require_release(ctx, args["release_id"])
    cs = _changes_for(ctx, rel)
    return {
        "version": cs.version,
        "previous_version": cs.previous_version,
        "umbrella_repo": cs.umbrella_repo,
        "old_tag": cs.old_tag,
        "new_tag": cs.new_tag,
        "baseline_missing": cs.baseline_missing,
        "components": [_component_summary(c) for c in cs.components],
        "unmatched_dependencies": cs.unmatched_dependencies,
        "library_repos": [r["repo"] for r in cs.library_repos],
    }


def _list_component_commits(ctx: ToolContext, args: dict) -> Any:
    rel = _require_release(ctx, args["release_id"])
    cs = _changes_for(ctx, rel)
    wanted = (args.get("component") or "").strip()
    change = next((c for c in cs.components if c.name == wanted), None)
    if change is None:
        known = ", ".join(c.name for c in cs.components) or "(none)"
        raise release_ops.ReleaseActionError(
            404, f"No component '{wanted}' in this release's change-set. "
                 f"Components: {known}"
        )
    if change.status == "error":
        raise release_ops.ReleaseActionError(502, change.error)
    commits = change.commits[:_COMMIT_LIMIT]
    return {
        "component": change.name,
        "old_version": change.old_version,
        "new_version": change.new_version,
        "total": change.commit_count,
        "truncated": change.commits_truncated or len(change.commits) > _COMMIT_LIMIT,
        "compare_url": change.compare_url,
        "commits": [
            {
                "short_sha": k.short_sha,
                "subject": k.subject[:_SUBJECT_LIMIT],
                "author": k.author,
                "tickets": k.tickets,
                "url": k.url,
            }
            for k in commits
        ],
    }


def _get_ticket_mapping(ctx: ToolContext, args: dict) -> Any:
    """Coverage report: which commits reference a ticket and which do not.
    Unmapped commits are reported explicitly — never guessed at."""
    rel = _require_release(ctx, args["release_id"])
    cs = _changes_for(ctx, rel)
    components = []
    mapped = unmapped = 0
    for c in cs.components:
        if c.status not in ("changed", "error"):
            continue
        entry = {
            "name": c.name,
            "status": c.status,
            "error": c.error,
            "mapped": c.mapped_count,
            "unmapped": c.unmapped_count,
            "tickets": sorted({t for k in c.commits for t in k.tickets}),
            "unmapped_subjects": [
                k.subject[:_SUBJECT_LIMIT] for k in c.commits if not k.tickets
            ][:_UNMAPPED_SAMPLE],
        }
        mapped += c.mapped_count
        unmapped += c.unmapped_count
        components.append(entry)
    return {
        "version": cs.version,
        "previous_version": cs.previous_version,
        "baseline_missing": cs.baseline_missing,
        "total_mapped": mapped,
        "total_unmapped": unmapped,
        "components": components,
    }


def _run_code_review(ctx: ToolContext, args: dict) -> Any:
    """Run the advisory AI review and attach the report to the release. The
    report body is not echoed to the model — the document card is the result."""
    rel = _require_release(ctx, args["release_id"])
    try:
        result = code_review.run_code_review(ctx.conn, ctx.cfg, ctx.principal, rel)
    except (git_changes.ChangesUnavailable, code_review.ReviewUnavailable) as exc:
        raise release_ops.ReleaseActionError(400, str(exc)) from exc
    except GitNotConfigured as exc:
        raise release_ops.ReleaseActionError(
            503, f"The git hosting cannot be queried: {exc}"
        ) from exc
    except GitUnreachable as exc:
        raise release_ops.ReleaseActionError(
            502, f"Git hosting query failed: {exc}"
        ) from exc
    except RuntimeError as exc:  # LLM engine not configured
        raise release_ops.ReleaseActionError(503, str(exc)) from exc
    meta = result["document"]
    return {
        "title": meta["title"],
        "status": meta["status"],
        "latest_version": meta["latest_version"],
        "components_reviewed": result["components_reviewed"],
        "components_skipped": result["components_skipped"],
        "unmapped_commits": result["unmapped_commits"],
        "document_ref": _document_ref(rel["id"], meta),
    }


# --- Tool registry ----------------------------------------------------------
def _tool(name, description, handler, properties=None, required=None) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        input_schema={
            "type": "object",
            "properties": properties or {},
            "required": required or [],
        },
        handler=handler,
    )


_PRODUCT_SELECTOR = {
    "product_id": {"type": "integer", "description": "Product id to scope to"},
    "product_name": {"type": "string", "description": "Product name (used if id is omitted)"},
}


def build_tools() -> list[ToolSpec]:
    """The full toolbox exposed to the model. Static — the handlers receive the
    per-request :class:`ToolContext` at call time via the dispatcher."""
    return [
        _tool("list_products", "List all products with their id and tracker repo.",
              _list_products),
        _tool("list_releases",
              "List releases, optionally scoped to a product by id or name.",
              _list_releases, _PRODUCT_SELECTOR),
        _tool("get_release_status",
              "Full status of one release: state, open issues, documents, "
              "blockers and the actions performed on it.",
              _get_release_status,
              {"release_id": {"type": "integer"}}, ["release_id"]),
        _tool("project_status_report",
              "Status report of every running (non-final) release: current state, "
              "actions performed, and all blockers. Optionally scope to one product.",
              _project_status_report, _PRODUCT_SELECTOR),
        _tool("list_release_issues", "List the tracked issues (tickets) of a release.",
              _list_release_issues,
              {"release_id": {"type": "integer"}}, ["release_id"]),
        _tool("list_documents",
              "List the documents attached to a release, each with its approval "
              "status (DRAFT/APPROVED) and available download formats.",
              _list_documents,
              {"release_id": {"type": "integer"}}, ["release_id"]),
        _tool("get_document",
              "Fetch one document (by document_id or title) so the operator can "
              "download it — the UI shows Markdown/PDF download buttons for the "
              "result. Also reports its approval status.",
              _get_document,
              {"release_id": {"type": "integer"},
               "document_id": {"type": "integer"},
               "title": {"type": "string", "description": "Document title (used if document_id omitted)"}},
              ["release_id"]),
        _tool("approve_document",
              "Approve a release document (mark it APPROVED). Documents start as "
              "DRAFT; approve one only when the operator asks to.",
              _approve_document,
              {"release_id": {"type": "integer"},
               "document_id": {"type": "integer"},
               "title": {"type": "string", "description": "Document title (used if document_id omitted)"}},
              ["release_id"]),
        _tool("list_document_types",
              "List the configured document types, each flagged as 'automatic' "
              "(the assistant can generate it) or 'manual' (an operator uploads it).",
              _list_document_types),
        _tool("get_generation_prompt",
              "Before generating a document, check the document type is supported and "
              "set to automatic generation, and get its generation prompt. Fails with a "
              "clear reason if the type is unknown or manual — relay that to the operator.",
              _get_generation_prompt,
              {"doc_type": {"type": "string", "description": "The document type to generate"}},
              ["doc_type"]),
        _tool("get_issue",
              "Full detail of one ticket: its key, summary, description, status and "
              "a link to the ticket in the ticketing system. Use this whenever the "
              "operator asks about a specific ticket, and always give them the link.",
              _get_issue,
              {"release_id": {"type": "integer"},
               "key": {"type": "string", "description": "Issue key, e.g. 'REL-1' or '#12'"}},
              ["release_id", "key"]),
        _tool("add_issue_to_release",
              "Add a ticket to a release. A ticket belongs to a release when it "
              "matches the release's search criteria, so this EDITS THE TICKET in the "
              "ticketing system until it does — e.g. for a release whose criteria is "
              "label = v0.0.1, it adds the label v0.0.1 to the ticket. Tell the "
              "operator which edit was made.",
              _add_issue_to_release,
              {"release_id": {"type": "integer"},
               "key": {"type": "string", "description": "Issue key, e.g. 'REL-1' or '#12'"}},
              ["release_id", "key"]),
        _tool("remove_issue_from_release",
              "Remove a ticket from a release by editing it so it no longer matches "
              "the release's criteria — e.g. for criteria label = v0.0.1, the label "
              "v0.0.1 is removed from the ticket. The ticket itself is not deleted. "
              "Tell the operator which edit was made.",
              _remove_issue_from_release,
              {"release_id": {"type": "integer"},
               "key": {"type": "string", "description": "Issue key, e.g. 'REL-1' or '#12'"}},
              ["release_id", "key"]),
        _tool("search_issues",
              "Preview the tickets a search criteria selects in the ticketing system, "
              "before binding it to a release. Use this to show the operator what a "
              "criteria finds and confirm it is the right work.",
              _search_issues,
              {"product_id": {"type": "integer"},
               "criteria_mode": {"type": "string",
                                 "description": "GitHub: 'milestone' or 'label'. Jira: 'label' or 'jql'."},
               "criteria_value": {"type": "string",
                                  "description": "What to search for, e.g. 'v0.0.1'"}},
              ["product_id", "criteria_mode", "criteria_value"]),
        _tool("set_release_criteria",
              "Change which tickets a release contains, by changing its search "
              "criteria. Returns the tickets the new criteria selects.",
              _set_release_criteria,
              {"release_id": {"type": "integer"},
               "criteria_mode": {"type": "string",
                                 "description": "GitHub: 'milestone' or 'label'. Jira: 'label' or 'jql'."},
               "criteria_value": {"type": "string"}},
              ["release_id", "criteria_mode", "criteria_value"]),
        _tool("create_release",
              "Create a new release for a product in the initial workflow state. The "
              "search criteria is required: it is what says which tickets the release "
              "contains (e.g. label = v0.0.1), and every later question about its "
              "issues is put to the ticketing system with it. Preview the tickets with "
              "search_issues and confirm them with the operator first.",
              _create_release,
              {"product_id": {"type": "integer"},
               "version": {"type": "string"},
               "short_description": {"type": "string"},
               "criteria_mode": {"type": "string",
                                 "description": "GitHub: 'milestone' or 'label'. Jira: 'label' or 'jql'."},
               "criteria_value": {"type": "string",
                                  "description": "What to search for, e.g. 'v0.0.1'"}},
              ["product_id", "version", "criteria_mode", "criteria_value"]),
        _tool("upload_document",
              "Attach a text/Markdown document to a release. Provide the document "
              "body as `content`. `doc_type` must be one of list_document_types.",
              _upload_document,
              {"release_id": {"type": "integer"},
               "doc_type": {"type": "string"},
               "title": {"type": "string"},
               "content": {"type": "string", "description": "Document body (text/Markdown)"},
               "filename": {"type": "string"}},
              ["release_id", "doc_type", "title", "content"]),
        _tool("link_attachment_as_new_document",
              "Link a file the operator attached in the chat to a release as a NEW "
              "document (its first version). Use it only when the release has no "
              "document for this file yet — otherwise use "
              "link_attachment_as_new_version. `attachment_id` comes from the "
              "attached-files list in the conversation context; `doc_type` must be "
              "one of list_document_types; `title` defaults to the file name. "
              "Confirm the release, document title and type with the operator "
              "before calling this.",
              _link_attachment_as_new_document,
              {"release_id": {"type": "integer"},
               "attachment_id": {"type": "integer",
                                 "description": "Id of the file the operator attached"},
               "doc_type": {"type": "string"},
               "title": {"type": "string",
                         "description": "Document title (defaults to the file name)"}},
              ["release_id", "attachment_id", "doc_type"]),
        _tool("link_attachment_as_new_version",
              "Link a file the operator attached in the chat as the NEXT VERSION of "
              "an existing document on a release (identify it by document_id or "
              "title; earlier versions stay downloadable). The version number is "
              "assigned automatically and the document returns to DRAFT. Confirm "
              "with the operator which document the file updates before calling this.",
              _link_attachment_as_new_version,
              {"release_id": {"type": "integer"},
               "attachment_id": {"type": "integer",
                                 "description": "Id of the file the operator attached"},
               "document_id": {"type": "integer"},
               "title": {"type": "string",
                         "description": "Document title (used if document_id omitted)"}},
              ["release_id", "attachment_id"]),
        _tool("transition_release",
              "Apply a workflow transition to a release (e.g. 'Ready', 'Approve'). "
              "Role and readiness guards are enforced. Pass the operator's comment "
              "for the state change as `note`; ask the operator for one if they "
              "have not provided it.",
              _transition_release,
              {"release_id": {"type": "integer"},
               "transition": {"type": "string"},
               "note": {"type": "string",
                        "description": "The operator's comment explaining this "
                                       "state change (ask for it if not given)"}},
              ["release_id", "transition"]),
        _tool("get_release_changes",
              "The code changes a release ships, read live from git: which "
              "components (services) changed and their old→new versions, from the "
              "umbrella Helm chart diffed between the previous release's tag and "
              "this one's — or, for a simple single-repo product, its codebase "
              "repository diffed directly between the two release tags. Also "
              "reports Chart.yaml dependencies with no linked repository and why "
              "a baseline may be missing — relay those to the operator instead of "
              "treating them as 'no changes'.",
              _get_release_changes,
              {"release_id": {"type": "integer"}}, ["release_id"]),
        _tool("list_component_commits",
              "The commits of one changed component in a release (between its two "
              "version tags), each with the tickets it references and a link. "
              "Component names come from get_release_changes.",
              _list_component_commits,
              {"release_id": {"type": "integer"},
               "component": {"type": "string",
                             "description": "Component name from get_release_changes"}},
              ["release_id", "component"]),
        _tool("get_ticket_mapping",
              "Ticket-mapping coverage of a release's code changes: per component, "
              "how many commits reference a ticket (via commit message or branch "
              "name) and which do not. Unmapped commits are listed by subject — "
              "report them explicitly, never guess a ticket for them.",
              _get_ticket_mapping,
              {"release_id": {"type": "integer"}}, ["release_id"]),
        _tool("run_code_review",
              "Run the advisory AI code review over a release's changes: each "
              "changed component's diff is reviewed for possible bugs, risky "
              "changes and ticket inconsistencies, and the report is attached to "
              "the release as a DRAFT 'Code Review Report' document (a new "
              "version on re-runs). Advisory only — it blocks nothing. Slow: one "
              "LLM pass per changed component; tell the operator it may take a "
              "while before calling it.",
              _run_code_review,
              {"release_id": {"type": "integer"}}, ["release_id"]),
    ]


# Tools that change the system (everything else only reads it). Drives the
# read/action badge on the "Assistant actions" configuration page.
# Note that add/remove_issue_to/from_release are writes to the *ticketing system*,
# not just to Release-It: they edit the operator's tickets.
_WRITE_TOOLS = {"create_release", "upload_document", "transition_release",
                "set_release_criteria", "approve_document",
                "add_issue_to_release", "remove_issue_from_release",
                "run_code_review",
                "link_attachment_as_new_document", "link_attachment_as_new_version"}


def describe_actions() -> list[dict]:
    """The assistant's capabilities, described from the live tool registry so
    the configuration page can never drift from what the model can actually do."""
    return [
        {
            "name": t.name,
            "kind": "action" if t.name in _WRITE_TOOLS else "read",
            "description": t.description,
        }
        for t in build_tools()
    ]


# Ready-to-use prompt templates for the assistant's main jobs, shown on the
# LLM engine page. Placeholders in <angle brackets> are filled by the operator.
PROMPT_TEMPLATES: list[dict] = [
    {
        "key": "generate_document",
        "title": "Generate and upload a document",
        "description": "Generate a supported document from its own configured prompt "
                       "and attach it to a release.",
        "prompt": (
            "Generate the <document type> document for release <version> of <product>. "
            "First verify the document type with get_generation_prompt: it confirms the "
            "type is supported and set to automatic generation and returns the prompt to "
            "follow. If the type does not exist or is set to manual, tell the operator "
            "exactly why it cannot be generated and stop. Otherwise follow that "
            "document type's generation prompt to build the document in Markdown — "
            "reading the release's issues from the ticketing system if the prompt relies "
            "on them, and referencing each issue by its key. Once generated, upload it to "
            "the release as a document of that type, titled after the document and "
            "version."
        ),
    },
    {
        "key": "release_status",
        "title": "Release status",
        "description": "A full picture of where a release stands and what is "
                       "blocking it.",
        "prompt": (
            "What is the status of release <version> of <product>? Report its "
            "current workflow state, whether it is ready to move forward, the "
            "open issues, the documents already uploaded (and any required ones "
            "still missing), and the actions performed on it so far."
        ),
    },
    {
        "key": "code_review",
        "title": "Review the code changes",
        "description": "Report what code a release ships, its ticket coverage, "
                       "and run the advisory AI code review.",
        "prompt": (
            "Review the code changes of release <version> of <product>. First "
            "report the changed components with their old and new versions "
            "(get_release_changes) and the ticket-mapping coverage, listing any "
            "commits with no ticket reference and any Chart.yaml dependencies "
            "with no linked repository. Then run the AI code review "
            "(run_code_review) and confirm the report attached to the release — "
            "do not paste the report body; the operator downloads it from the "
            "document card. If the changes cannot be computed (no umbrella "
            "repository, missing tag, hosting unreachable), relay the exact "
            "reason instead of treating it as 'no changes'."
        ),
    },
    {
        "key": "advance_workflow",
        "title": "Advance the workflow",
        "description": "Move a release to its next state in the configured "
                       "workflow, respecting roles and readiness guards.",
        "prompt": (
            "Advance release <version> of <product> to the next step of the "
            "configured workflow. Check its status and blockers first; if a "
            "transition is available and all its requirements are met, apply it "
            "and confirm the new state. If it is blocked, list exactly what must "
            "be resolved before it can advance."
        ),
    },
]


# --- Attached-file context ---------------------------------------------------
# How much of a text file to show the model. Enough for it to recognise what the
# document is (a title, a heading, the first lines) without feeding a whole file
# into the context on every turn — the bytes it links are read from the staging
# table, never from this preview.
_PREVIEW_CHARS = 600
_TEXTUAL_TYPES = ("text/", "application/json", "application/xml")


def _is_textual(content_type: str) -> bool:
    return (content_type or "").lower().startswith(_TEXTUAL_TYPES)


def render_attachment_context(conn, attachments: list[dict]) -> str:
    """The files the operator has attached and not yet linked, as a system-prompt
    block. This is the model's only view of them: it sees the metadata (and, for
    text files, an opening excerpt) and passes the ``attachment_id`` back to the
    link tools — the content itself never travels through the transcript."""
    if not attachments:
        return ""
    lines = [
        "## Files attached by the operator (not yet linked to a document)",
        "Each is staged and waiting. Follow the attached-file rules in the "
        "guidelines above: work out what it is, confirm, link, then ask about "
        "approval.",
        "",
    ]
    for a in attachments:
        lines.append(
            f'- attachment_id={a["id"]}: "{a["filename"]}" '
            f'({a["content_type"]}, {a["size"]} bytes, uploaded {a["created_at"]})'
        )
        if _is_textual(a["content_type"]):
            content = chat_attachments_repo.content_of(conn, a["id"]) or b""
            excerpt = content.decode("utf-8", errors="replace")[:_PREVIEW_CHARS].strip()
            if excerpt:
                lines.append(f"  Opening excerpt (for identification only):\n  ```\n{excerpt}\n  ```")
    return "\n".join(lines)


# The prompt fields an admin may override (the key is structural and fixed).
_PROMPT_FIELDS = ("title", "description", "prompt")


def effective_prompts(overrides: dict[str, dict] | None = None) -> list[dict]:
    """The prompt templates with any admin overrides applied on top of the
    built-in defaults. Only the known keys and known fields are honoured, so the
    result always has the default shape with title/description/prompt possibly
    replaced. A blank override field falls back to the default."""
    overrides = overrides or {}
    result: list[dict] = []
    for tmpl in PROMPT_TEMPLATES:
        ov = overrides.get(tmpl["key"]) or {}
        merged = dict(tmpl)
        for field in _PROMPT_FIELDS:
            val = ov.get(field)
            if isinstance(val, str) and val.strip():
                merged[field] = val
        result.append(merged)
    return result


def render_job_playbook(prompts: list[dict]) -> str:
    """A system-prompt section that turns the predefined prompt templates into
    *runnable jobs*: it teaches the assistant to recognise when an operator's
    request matches one (in any language, even phrased loosely), to say so
    explicitly, and to narrate the concrete actions it performs while running it.

    ``prompts`` is the effective (admin-overridden) template list from
    :func:`effective_prompts`, so the playbook always tracks the live wording."""
    lines = [
        "# Predefined jobs",
        "The requests below are standard jobs. Recognise the operator's intent even "
        "when it is phrased loosely, with typos, or in another language — e.g. the "
        'Italian "crea le release notes per il progetto Dummy", or "create a release '
        'note", both map to the "Generate and upload a document" job (with "release '
        'notes" as the document type). Any request to produce a supported document '
        "maps to that same job, driven by the document type's own generation prompt.",
        "",
        "When an operator's message matches a job, do all of the following:",
        "1. State explicitly, in your reply, which job you are running — by its exact "
        'title (e.g. "Running the **Generate and upload release notes** job for '
        'Dummy v0.0.1").',
        "2. Carry out that job's steps by calling the tools.",
        "3. As you go, describe each concrete action you take — the tool and its key "
        'arguments (e.g. "Syncing issues with label v0.0.1", "Generating the release '
        'notes document", "Uploading it as \\"Release Notes v0.0.1\\"").',
        "4. Substitute the <placeholders> with details from the request; if a detail "
        "needed to run the job (product, version) is missing, ask for it first.",
        "5. When a job produces a document, the uploaded document is the result — do "
        "not paste or preview its body in your reply. Confirm what you uploaded (title "
        "and type) and let the operator download it from the document card.",
        "",
        "Available jobs:",
    ]
    for p in prompts:
        lines.append(f'## {p["title"]}')
        if p.get("description"):
            lines.append(p["description"])
        lines.append(f'Steps: {p["prompt"]}')
        lines.append("")
    return "\n".join(lines).strip()


def prompt_override_for(key: str, patch: dict) -> dict:
    """Reduce a full prompt (title/description/prompt) to just the fields that
    differ from the built-in default for ``key`` — so untouched prompts keep
    tracking the default and 'reset to default' stores nothing. Returns {} for an
    unknown key so the caller can reject it."""
    default = next((t for t in PROMPT_TEMPLATES if t["key"] == key), None)
    if default is None:
        return {}
    entry: dict[str, str] = {}
    for field in _PROMPT_FIELDS:
        val = patch.get(field)
        if val is None:
            continue
        # Titles/descriptions are single-line; keep prompt bodies verbatim.
        val = val if field == "prompt" else val.strip()
        if val.strip() and val != default[field]:
            entry[field] = val
    return entry


_ACTION_SUMMARY: dict[str, str] = {
    "list_products": "Listed products",
    "list_releases": "Listed releases",
    "get_release_status": "Read release status",
    "project_status_report": "Compiled status report",
    "list_release_issues": "Listed release issues",
    "list_documents": "Listed documents",
    "list_document_types": "Listed document types",
    "get_generation_prompt": "Checked the document type's generation prompt",
    "sync_release_issues": "Synced issues from tracker",
    "get_document": "Prepared document for download",
    "get_release_changes": "Computed release code changes",
    "list_component_commits": "Listed component commits",
    "get_ticket_mapping": "Reported ticket-mapping coverage",
}


def _summarize(name: str, result: Any, ok: bool) -> str:
    if not ok:
        detail = result.get("error") if isinstance(result, dict) else ""
        return f"{name} failed: {detail}".strip().rstrip(":")
    if name == "create_release" and isinstance(result, dict):
        return f"Created release v{result.get('version')} (#{result.get('id')})"
    if name == "upload_document" and isinstance(result, dict):
        return f"Uploaded document “{result.get('title')}” ({result.get('doc_type')})"
    if name == "transition_release" and isinstance(result, dict):
        return f"Moved release #{result.get('id')} to “{result.get('state')}”"
    if name == "approve_document" and isinstance(result, dict):
        return f"Approved document “{result.get('title')}”"
    if name == "get_document" and isinstance(result, dict):
        return f"Prepared “{result.get('title')}” for download"
    if name in {"link_attachment_as_new_document", "link_attachment_as_new_version"} and isinstance(result, dict):
        return (f"Linked “{result.get('filename')}” to “{result.get('title')}” "
                f"({result.get('doc_type')}) as version {result.get('version')}")
    if name == "run_code_review" and isinstance(result, dict):
        return (f"Generated “{result.get('title')}” "
                f"({result.get('components_reviewed')} component(s) reviewed)")
    return _ACTION_SUMMARY.get(name, name)


def make_dispatcher(ctx: ToolContext) -> tuple[Dispatch, list[ToolSpec]]:
    """Build the (dispatch, tools) pair for one chat request. ``dispatch`` runs a
    named tool in its own savepoint and returns ``(result_for_model, action)``."""
    tools = build_tools()
    registry = {t.name: t for t in tools}

    def dispatch(name: str, args: dict) -> tuple[Any, ActionRecord]:
        spec = registry.get(name)
        if spec is None:
            result = {"error": f"Unknown tool '{name}'"}
            return result, ActionRecord(tool=name, ok=False, summary=f"Unknown tool '{name}'")
        try:
            with ctx.conn.transaction():
                result = spec.handler(ctx, args or {})
            doc_ref = result.get("document_ref") if isinstance(result, dict) else None
            return result, ActionRecord(
                tool=name, ok=True, summary=_summarize(name, result, True), document=doc_ref
            )
        except release_ops.ReleaseActionError as exc:
            result = {"error": exc.detail}
            return result, ActionRecord(tool=name, ok=False, summary=exc.detail)
        except Exception as exc:  # surfaced to the model so it can recover/report
            log.exception("assistant tool %s failed", name)
            result = {"error": f"{type(exc).__name__}: {exc}"}
            return result, ActionRecord(tool=name, ok=False, summary=_summarize(name, result, False))

    return dispatch, tools
