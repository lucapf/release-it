"""Linking a file the operator attached in the chat to a release document.

The chat transcript is text-only, so an attached file is staged in
``chat_attachment`` and the model only ever sees its metadata plus the
``attachment_id``. These tests cover the two link tools — the ones that turn a
staged file into a document version — with the repositories faked, so the rules
they enforce (ownership, single use, new-document vs new-version) are asserted
directly rather than through a database.
"""
from __future__ import annotations

from datetime import datetime

from app.core.identity import Principal
from app.services import assistant, release_ops


def _ctx(conn=object(), subject="op"):
    return assistant.ToolContext(
        conn=conn, principal=Principal(subject, set()), sm=None, cfg=None
    )


def _attachment(**over):
    base = {
        "id": 7,
        "filename": "test-report.pdf",
        "content_type": "application/pdf",
        "size": 12,
        "uploaded_by": "op",
        "created_at": datetime(2026, 7, 14, 9, 0),
        "linked_document_id": None,
        "linked_at": None,
    }
    return {**base, **over}


class _Repos:
    """The repository calls the link tools make, recorded so we can assert on them."""

    def __init__(self, monkeypatch, attachment=None, existing_doc=None, doc_types=("Test Report",)):
        self.attachment = attachment if attachment is not None else _attachment()
        self.existing_doc = existing_doc  # what find_document/get_document returns
        self.versions: list[dict] = []
        self.linked: list[tuple[int, int]] = []
        self.created: list[dict] = []

        monkeypatch.setattr(assistant.releases_repo, "get",
                            lambda conn, rid: {"id": rid, "version": "1.0.0", "state": "Draft"})
        monkeypatch.setattr(assistant.config_repo, "document_type_names",
                            lambda conn: set(doc_types))
        monkeypatch.setattr(assistant.chat_attachments_repo, "get",
                            lambda conn, aid: self.attachment if aid == self.attachment["id"] else None)
        monkeypatch.setattr(assistant.chat_attachments_repo, "content_of",
                            lambda conn, aid: b"file-bytes")
        monkeypatch.setattr(assistant.chat_attachments_repo, "mark_linked", self._mark_linked)
        monkeypatch.setattr(assistant.documents_repo, "find_document",
                            lambda conn, rid, title: self.existing_doc)
        monkeypatch.setattr(assistant.documents_repo, "get_document",
                            lambda conn, did: self.existing_doc)
        monkeypatch.setattr(assistant.documents_repo, "create_document", self._create_document)
        monkeypatch.setattr(assistant.documents_repo, "add_version", self._add_version)
        monkeypatch.setattr(assistant.documents_repo, "get_document_meta", self._get_meta)
        # The PDF companion is only rendered for Markdown sources; irrelevant here.
        monkeypatch.setattr(assistant.doc_render, "pdf_for",
                            lambda ct, content, filename=None, title="": None)

    def _mark_linked(self, conn, attachment_id, document_id):
        # Mirrors the repo's "only if unlinked" UPDATE: a second link is a no-op.
        if self.attachment["linked_at"] is not None:
            return None
        self.linked.append((attachment_id, document_id))
        self.attachment["linked_at"] = datetime(2026, 7, 14, 9, 5)
        self.attachment["linked_document_id"] = document_id
        return self.attachment

    def _create_document(self, conn, release_id, title, doc_type):
        doc = {"id": 42, "release_id": release_id, "title": title, "doc_type": doc_type}
        self.created.append(doc)
        return doc

    def _add_version(self, conn, document_id, filename, content_type, content, uploaded_by, pdf=None):
        version = {"id": 100 + len(self.versions), "document_id": document_id,
                   "version": len(self.versions) + 1, "filename": filename,
                   "content_type": content_type, "content": content,
                   "uploaded_by": uploaded_by}
        self.versions.append(version)
        return version

    def _get_meta(self, conn, document_id):
        latest = self.versions[-1]
        title = self.created[0]["title"] if self.created else self.existing_doc["title"]
        doc_type = self.created[0]["doc_type"] if self.created else self.existing_doc["doc_type"]
        return {"id": document_id, "title": title, "doc_type": doc_type, "status": "DRAFT",
                "latest_version": latest["version"], "latest_version_id": latest["id"],
                "latest_filename": latest["filename"], "latest_pdf_size": 0, "version_count": 1}


# --- New document -----------------------------------------------------------
def test_link_as_new_document_stores_the_file_and_spends_the_attachment(monkeypatch):
    repos = _Repos(monkeypatch)

    out = assistant._link_attachment_as_new_document(
        _ctx(), {"release_id": 3, "attachment_id": 7, "doc_type": "Test Report"}
    )

    # The staged bytes became version 1 of a new document, titled after the file.
    assert repos.created == [{"id": 42, "release_id": 3, "title": "test-report.pdf",
                             "doc_type": "Test Report"}]
    assert repos.versions[0]["content"] == b"file-bytes"
    assert repos.versions[0]["content_type"] == "application/pdf"
    assert repos.versions[0]["uploaded_by"] == "op"
    # The attachment is spent, so it can't become a second document.
    assert repos.linked == [(7, 42)]
    # It lands as a DRAFT — the assistant then asks the operator about approval.
    assert out["status"] == "DRAFT"
    assert out["version"] == 1
    assert out["attachment_id"] == 7
    # And carries the reference the chat UI renders as a download button.
    assert out["document_ref"]["document_id"] == 42
    assert out["document_ref"]["filename"] == "test-report.pdf"


def test_link_as_new_document_honours_an_explicit_title(monkeypatch):
    repos = _Repos(monkeypatch)

    assistant._link_attachment_as_new_document(
        _ctx(),
        {"release_id": 3, "attachment_id": 7, "doc_type": "Test Report",
         "title": "QA Sign-off 1.0.0"},
    )
    assert repos.created[0]["title"] == "QA Sign-off 1.0.0"


def test_link_as_new_document_rejects_an_unsupported_type(monkeypatch):
    _Repos(monkeypatch, doc_types=("Test Report",))
    try:
        assistant._link_attachment_as_new_document(
            _ctx(), {"release_id": 3, "attachment_id": 7, "doc_type": "Invoice"}
        )
        assert False, "expected an unsupported document type to be rejected"
    except release_ops.ReleaseActionError as exc:
        assert exc.status_code == 400
        assert "Invoice" in exc.detail


def test_link_as_new_document_points_at_the_version_tool_when_the_title_exists(monkeypatch):
    # A document with this title is already on the release: this file is a new
    # version of it, not a second document — and the error says so.
    _Repos(monkeypatch, existing_doc={"id": 9, "release_id": 3, "title": "test-report.pdf",
                                      "doc_type": "Test Report"})
    try:
        assistant._link_attachment_as_new_document(
            _ctx(), {"release_id": 3, "attachment_id": 7, "doc_type": "Test Report"}
        )
        assert False, "expected a duplicate title to be rejected"
    except release_ops.ReleaseActionError as exc:
        assert exc.status_code == 409
        assert "new version" in exc.detail and "9" in exc.detail


# --- New version of an existing document ------------------------------------
def test_link_as_new_version_appends_to_the_existing_document(monkeypatch):
    repos = _Repos(monkeypatch, existing_doc={"id": 9, "release_id": 3,
                                              "title": "Test Report", "doc_type": "Test Report"})

    out = assistant._link_attachment_as_new_version(
        _ctx(), {"release_id": 3, "attachment_id": 7, "document_id": 9}
    )

    # No new document — the file was appended to the one that exists.
    assert repos.created == []
    assert repos.versions[0]["document_id"] == 9
    assert repos.linked == [(7, 9)]
    # add_version returns a document to DRAFT: the approved content just changed.
    assert out["status"] == "DRAFT"
    assert out["document_ref"]["document_id"] == 9


# --- Guards on the staged file ----------------------------------------------
def test_a_file_uploaded_by_another_operator_cannot_be_linked(monkeypatch):
    _Repos(monkeypatch, attachment=_attachment(uploaded_by="someone-else"))
    try:
        assistant._link_attachment_as_new_document(
            _ctx(subject="op"), {"release_id": 3, "attachment_id": 7, "doc_type": "Test Report"}
        )
        assert False, "expected another operator's attachment to be refused"
    except release_ops.ReleaseActionError as exc:
        assert exc.status_code == 403


def test_an_already_linked_file_cannot_be_linked_again(monkeypatch):
    _Repos(monkeypatch, attachment=_attachment(linked_at=datetime(2026, 7, 14, 9, 5),
                                               linked_document_id=42))
    try:
        assistant._link_attachment_as_new_document(
            _ctx(), {"release_id": 3, "attachment_id": 7, "doc_type": "Test Report"}
        )
        assert False, "expected a spent attachment to be refused"
    except release_ops.ReleaseActionError as exc:
        assert exc.status_code == 409
        assert "already been linked" in exc.detail


def test_an_unknown_attachment_is_reported_not_guessed(monkeypatch):
    _Repos(monkeypatch)
    try:
        assistant._link_attachment_as_new_document(
            _ctx(), {"release_id": 3, "attachment_id": 999, "doc_type": "Test Report"}
        )
        assert False, "expected an unknown attachment to be refused"
    except release_ops.ReleaseActionError as exc:
        assert exc.status_code == 404


# --- What the model is shown -------------------------------------------------
def test_attachment_context_lists_files_and_excerpts_text(monkeypatch):
    monkeypatch.setattr(assistant.chat_attachments_repo, "content_of",
                        lambda conn, aid: b"# Test Report\n\nAll suites passed.")
    block = assistant.render_attachment_context(
        object(),
        [_attachment(id=7, filename="report.md", content_type="text/markdown", size=34)],
    )
    assert "attachment_id=7" in block and "report.md" in block
    # A text file gets an excerpt so the model can tell what document it is.
    assert "All suites passed." in block


def test_attachment_context_does_not_excerpt_binary_files(monkeypatch):
    monkeypatch.setattr(assistant.chat_attachments_repo, "content_of",
                        lambda conn, aid: b"%PDF-1.7\x00\x01binary")
    block = assistant.render_attachment_context(object(), [_attachment()])
    assert "attachment_id=7" in block and "test-report.pdf" in block
    assert "excerpt" not in block.lower()


def test_no_attachments_means_no_context_block():
    assert assistant.render_attachment_context(object(), []) == ""


def test_link_tools_are_flagged_as_actions_not_reads():
    described = {a["name"]: a for a in assistant.describe_actions()}
    assert described["link_attachment_as_new_document"]["kind"] == "action"
    assert described["link_attachment_as_new_version"]["kind"] == "action"
