-- Document management with versioning.
-- A `document` is a logical, named file attached to a release, classified by a
-- supported document type (set once, fixed across versions). Each upload is a
-- new immutable `document_version` row (content stored in-DB as bytea, like
-- artifacts/documentation). Re-uploading to the same document increments its
-- version; every previous version stays downloadable. There is no edit-in-place:
-- changes are made outside the system and uploaded as a new version.

-- The supported document types operators may mark a document with. Admin-managed
-- on the configuration page (like check_template), so the set is not fixed in
-- code. Seeded with a sensible default set below.
CREATE TABLE document_type (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name       TEXT        NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO document_type (name) VALUES
    ('Release Notes'), ('Runbook'), ('Test Report'),
    ('Architecture'), ('User Manual'), ('Compliance'), ('Other');

CREATE TABLE document (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    release_id  BIGINT      NOT NULL REFERENCES release(id) ON DELETE CASCADE,
    title       TEXT        NOT NULL,
    -- The supported document type the operator marked this document with,
    -- validated against `document_type` at upload time. Stored as text so a
    -- later removal of a type from the config does not rewrite history.
    doc_type    TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (release_id, title)
);

CREATE TABLE document_version (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id   BIGINT      NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    version       INT         NOT NULL,
    filename      TEXT        NOT NULL,
    content_type  TEXT        NOT NULL DEFAULT 'application/octet-stream',
    content       BYTEA       NOT NULL,
    size          BIGINT      NOT NULL DEFAULT 0,
    uploaded_by   TEXT,                                   -- JWT subject of the uploader
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, version)
);

CREATE INDEX idx_document_release    ON document(release_id);
CREATE INDEX idx_docversion_document ON document_version(document_id);
