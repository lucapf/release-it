-- Documents gain an approval status and a rendered-PDF companion for each
-- version.
--
-- * status — every document starts as DRAFT (this is how auto-generated release
--   notes land); an operator promotes it to APPROVED from the UI or the chat.
--   Uploading a new version returns the document to DRAFT (see repo.add_version),
--   since the content it was approved on has changed.
-- * pdf_content / pdf_size — when a version's source is Markdown we render a PDF
--   alongside it so operators can download the PDF for reading and the Markdown
--   for editing. Non-Markdown uploads leave these NULL/0.

ALTER TABLE document
    ADD COLUMN status TEXT NOT NULL DEFAULT 'DRAFT'
    CHECK (status IN ('DRAFT', 'APPROVED'));

ALTER TABLE document_version ADD COLUMN pdf_content BYTEA;
ALTER TABLE document_version ADD COLUMN pdf_size BIGINT NOT NULL DEFAULT 0;
