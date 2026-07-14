-- Files the operator attaches in the chat, staged until the assistant links them
-- to a document.
--
-- The chat endpoint is stateless (the client posts the whole transcript each
-- turn) and the transcript carries text only, so an uploaded file cannot ride
-- along in it. Instead the file is staged here first and only its *metadata*
-- (id, filename, content type, size) is put in front of the model. The model
-- works out which release and which document the file belongs to, confirms that
-- with the operator, and then calls a link tool with the attachment_id — at
-- which point the bytes are copied into a document_version and the attachment is
-- marked linked (linked_document_id / linked_at).
--
-- An attachment is therefore a short-lived staging row, not a second store of
-- documents: once linked, `document_version` owns the content. Unlinked rows are
-- purged after CHAT_ATTACHMENT_TTL_HOURS (see repositories/chat_attachments.py),
-- so a file the operator uploaded but never linked does not linger.

CREATE TABLE chat_attachment (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    filename           TEXT        NOT NULL,
    content_type       TEXT        NOT NULL,
    content            BYTEA       NOT NULL,
    size               BIGINT      NOT NULL,
    -- The operator who uploaded it (gateway-asserted subject). A tool may only
    -- link an attachment uploaded by the operator it is acting for.
    uploaded_by        TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Set when the assistant links the file to a document. A linked attachment is
    -- spent: it cannot be linked a second time.
    linked_document_id BIGINT      REFERENCES document(id) ON DELETE SET NULL,
    linked_at          TIMESTAMPTZ
);

-- The lookup the chat does on every turn: this operator's still-pending files.
CREATE INDEX chat_attachment_pending_idx
    ON chat_attachment (uploaded_by, created_at)
    WHERE linked_at IS NULL;
