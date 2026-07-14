"""AI code review of a release's changes — advisory, never a gate.

Runs one single-shot LLM pass per changed component over the diff between its
two version tags (via :mod:`app.services.git_changes`), and assembles the
findings into a Markdown report stored as a versioned release document
("Code Review Report", DRAFT, with a PDF companion). Re-running the review adds
a new version of the same document; each run is recorded in the audit log.

The review is advisory: no workflow guard reads it, and its findings block
nothing. Diffs are budgeted, and every truncation is stated both in the prompt
(so the model knows its view is partial) and in the report (so the reader does
too) — a partial analysis must never present itself as a complete one.
"""
from __future__ import annotations

import logging

import psycopg

from app.core.identity import Principal
from app.integrations.llm import get_completion_service
from app.repositories import config as config_repo
from app.repositories import documents as documents_repo
from app.services import audit, doc_render, git_changes
from app.services.appconfig import EffectiveConfig
from app.services.git_changes import ComponentChange, ReleaseChangeSet

log = logging.getLogger("releaseit.code_review")

# The document type the report lands as (seeded by migration 0017).
REVIEW_DOC_TYPE = "Code Review Report"

# Per-component character budget for patch text in the prompt. Files are
# included whole, smallest first, until the budget is spent; the rest are
# listed by path so the model (and reader) know what was not analysed.
DIFF_BUDGET_CHARS = 60_000
_REVIEW_MAX_TOKENS = 4096

_REVIEW_SYSTEM = (
    "You are an advisory code reviewer for a release-management system. You are "
    "given one service's diff between two released versions, its commits and the "
    "tickets they reference. Report, in Markdown with these exact headings:\n"
    "### Findings — possible bugs, with the file path and the relevant hunk;\n"
    "### Risk notes — risky changes (migrations, concurrency, error handling, "
    "security, breaking API changes);\n"
    "### Ticket consistency — changes that look inconsistent with, or beyond the "
    "scope of, the tickets their commits reference.\n"
    "Be concrete and cite file paths. If a section has nothing to report, write "
    "'Nothing to report.' under it. If the diff is marked truncated or files are "
    "listed as not analysed, state explicitly that the analysis is partial. Never "
    "invent files, commits or tickets. Your review is advisory: it informs the "
    "operator, it does not decide."
)


class ReviewUnavailable(Exception):
    """The review cannot run at all (nothing to diff). The reason is the
    message, phrased for the operator."""


def _component_prompt(change: ComponentChange) -> str:
    """The user prompt for one component: commits with their tickets, then as
    much patch text as the budget allows (whole files, smallest first)."""
    lines = [
        f"Service: {change.name}",
        f"Version: {change.old_version} -> {change.new_version}",
        "",
        "Commits (with referenced tickets; '(no ticket)' means unmapped):",
    ]
    for c in change.commits:
        refs = ", ".join(c.tickets) if c.tickets else "(no ticket)"
        lines.append(f"- {c.short_sha} {c.subject} [{refs}]")
    if change.commits_truncated:
        lines.append(f"- ... commit list truncated ({change.commit_count} total)")

    files = (change.compare.files if change.compare else [])
    included, excluded, spent = [], [], 0
    for f in sorted(files, key=lambda f: len(f.patch)):
        if f.patch and spent + len(f.patch) <= DIFF_BUDGET_CHARS:
            included.append(f)
            spent += len(f.patch)
        else:
            excluded.append(f)

    lines += ["", "Diff:"]
    for f in included:
        header = f"--- {f.path} ({f.status}, +{f.additions}/-{f.deletions})"
        if f.truncated:
            header += " [TRUNCATED by the hosting or size cap]"
        lines += [header, "```diff", f.patch, "```"]
    if excluded:
        lines += ["", "Files NOT analysed (no patch available or diff budget exceeded):"]
        for f in excluded:
            lines.append(f"- {f.path} ({f.status}, +{f.additions}/-{f.deletions})")
    if change.compare and change.compare.files_truncated:
        lines.append("NOTE: the hosting withheld part of the file list — the diff is partial.")
    return "\n".join(lines)


def _coverage_table(cs: ReleaseChangeSet) -> list[str]:
    lines = [
        "| Component | Version | Commits | Mapped | Unmapped |",
        "|---|---|---:|---:|---:|",
    ]
    for c in cs.components:
        if c.status == "unchanged":
            continue
        version = {
            "changed": f"{c.old_version} -> {c.new_version}",
            "added": f"new in this release ({c.new_version})",
            "removed": f"removed (was {c.old_version})",
            "error": f"{c.old_version} -> {c.new_version} (error)",
        }[c.status]
        lines.append(
            f"| {c.name} | {version} | {c.commit_count} | "
            f"{c.mapped_count} | {c.unmapped_count} |"
        )
    return lines


def _assemble_report(
    rel: dict, cs: ReleaseChangeSet, sections: list[tuple[ComponentChange, str]]
) -> str:
    lines = [
        f"# Code Review Report — v{rel['version']}",
        "",
        f"Baseline: v{cs.previous_version} (tag `{cs.old_tag}`) → v{cs.version} "
        f"(tag `{cs.new_tag}`), umbrella chart `{cs.umbrella_repo}`.",
        "",
        "_Advisory review generated by AI. It informs the operator; it decides "
        "nothing and blocks nothing._",
        "",
        "## Changed components",
        "",
        *_coverage_table(cs),
    ]

    for change, review in sections:
        lines += [
            "",
            f"## {change.name} ({change.old_version} -> {change.new_version})",
            "",
            review.strip(),
        ]

    skipped = [c for c in cs.components if c.status == "error"]
    if skipped:
        lines += ["", "## Components not reviewed", ""]
        for c in skipped:
            lines.append(f"- **{c.name}**: {c.error}")

    unmapped = [
        (c.name, k) for c in cs.components for k in c.commits if not k.tickets
    ]
    lines += ["", "## Unmapped commits", ""]
    if unmapped:
        lines.append("Commits with no ticket reference — reported, never guessed:")
        for name, k in unmapped:
            lines.append(f"- `{k.short_sha}` ({name}) {k.subject}")
    else:
        lines.append("Every commit references a ticket.")

    if cs.unmatched_dependencies:
        lines += ["", "## Unmatched Chart.yaml dependencies", "",
                  "Dependencies with no linked component repository:"]
        for d in cs.unmatched_dependencies:
            lines.append(
                f"- **{d['name']}** ({d.get('old_version')} -> {d.get('new_version')})"
            )
    return "\n".join(lines)


def run_code_review(
    conn: psycopg.Connection,
    cfg: EffectiveConfig,
    principal: Principal,
    rel: dict,
) -> dict:
    """Compute the release's change-set, review each changed component, and
    store the report as a versioned document. Returns the document meta plus
    run counts.

    Raises :class:`ReviewUnavailable` when there is nothing to review, and lets
    the umbrella repo's Git errors propagate (the callers map them, exactly as
    for the changes endpoint).
    """
    cs = git_changes.compute_release_changes(conn, cfg, rel)
    if cs.baseline_missing:
        raise ReviewUnavailable(f"cannot review: {cs.baseline_missing}")
    changed = [c for c in cs.components if c.status == "changed" and c.compare]
    if not changed and not any(c.status == "error" for c in cs.components):
        raise ReviewUnavailable(
            f"nothing to review: no component changed between "
            f"v{cs.previous_version} and v{cs.version}"
        )

    llm = get_completion_service(cfg.llm)
    sections: list[tuple[ComponentChange, str]] = []
    for change in changed:
        review = llm.complete(
            _REVIEW_SYSTEM, _component_prompt(change), max_tokens=_REVIEW_MAX_TOKENS
        )
        sections.append((change, review))

    report = _assemble_report(rel, cs, sections)
    meta = _store_report(conn, principal, rel, report)
    audit.record(
        conn, entity_type="release", entity_id=rel["id"],
        action="code_review_generated", operator=principal.subject,
        new_value=meta["title"],
        note=f"{len(sections)} component(s) reviewed, "
             f"{sum(1 for c in cs.components if c.status == 'error')} skipped",
    )
    return {
        "document": meta,
        "components_reviewed": len(sections),
        "components_skipped": sum(1 for c in cs.components if c.status == "error"),
        "unmapped_commits": sum(c.unmapped_count for c in cs.components),
    }


def _store_report(
    conn: psycopg.Connection, principal: Principal, rel: dict, report: str
) -> dict:
    """Land the report as the release's Code Review Report document — a new
    document on the first run, a new DRAFT version on every re-run."""
    if REVIEW_DOC_TYPE not in config_repo.document_type_names(conn):
        # The type is seeded by migration; recreate it if an admin removed it.
        config_repo.add_document_type(conn, REVIEW_DOC_TYPE, "manual", "")
    title = f"Code Review Report v{rel['version']}"
    doc = documents_repo.find_document(conn, rel["id"], title)
    if doc is None:
        doc = documents_repo.create_document(conn, rel["id"], title, REVIEW_DOC_TYPE)
    content = report.encode("utf-8")
    filename = f"code-review-v{rel['version']}.md"
    pdf = doc_render.pdf_for(
        doc_render.MARKDOWN_CONTENT_TYPE, content, filename=filename, title=title
    )
    documents_repo.add_version(
        conn, doc["id"], filename, doc_render.MARKDOWN_CONTENT_TYPE, content,
        principal.subject or None, pdf,
    )
    return documents_repo.get_document_meta(conn, doc["id"])
