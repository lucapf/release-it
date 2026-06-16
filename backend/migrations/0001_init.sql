-- ReleaseIT initial schema.
-- Files (artifacts, documentation/release notes) are stored in-DB as bytea.
-- User/role data lives in the separate releaseit-auth service, NOT here.

-- Solution: optional container of products (gated by SOLUTION_ENABLED).
CREATE TABLE solution (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT        NOT NULL,
    version     TEXT        NOT NULL,                 -- SemVer
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE product (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT        NOT NULL UNIQUE,
    solution_id BIGINT      REFERENCES solution(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE release (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id        BIGINT      NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    version           TEXT        NOT NULL,            -- SemVer
    state             TEXT        NOT NULL,            -- current state name (validated against states.yaml)
    short_description TEXT        NOT NULL DEFAULT '',
    parent_release_id BIGINT      REFERENCES release(id) ON DELETE SET NULL,  -- release inheritance
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (product_id, version)
);

-- Pre/post installation checks attached to a release.
CREATE TABLE check_item (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    release_id  BIGINT      NOT NULL REFERENCES release(id) ON DELETE CASCADE,
    label       TEXT        NOT NULL,
    phase       TEXT        NOT NULL CHECK (phase IN ('pre', 'post')),
    done        BOOLEAN     NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Binary artifacts (helm charts, images metadata, bundles...) stored as bytea.
CREATE TABLE artifact (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    release_id    BIGINT      NOT NULL REFERENCES release(id) ON DELETE CASCADE,
    name          TEXT        NOT NULL,
    content_type  TEXT        NOT NULL DEFAULT 'application/octet-stream',
    content       BYTEA       NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Release notes / changelog / documentation, also stored in-DB.
CREATE TABLE documentation (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    release_id    BIGINT      NOT NULL REFERENCES release(id) ON DELETE CASCADE,
    name          TEXT        NOT NULL,
    content_type  TEXT        NOT NULL DEFAULT 'text/markdown',
    content       BYTEA       NOT NULL,
    is_draft      BOOLEAN     NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Target environments for installation.
CREATE TABLE environment (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT        NOT NULL UNIQUE,
    description TEXT        NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Audit log: every state-affecting action on Solution/Product/Release.
CREATE TABLE audit (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity_type   TEXT        NOT NULL,                -- 'solution' | 'product' | 'release'
    entity_id     BIGINT      NOT NULL,
    action        TEXT        NOT NULL,                -- e.g. 'status_update'
    old_value     TEXT,
    new_value     TEXT,
    operator      TEXT,                                -- JWT subject for manual actions
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_release_product   ON release(product_id);
CREATE INDEX idx_check_release     ON check_item(release_id);
CREATE INDEX idx_artifact_release  ON artifact(release_id);
CREATE INDEX idx_doc_release       ON documentation(release_id);
CREATE INDEX idx_audit_entity      ON audit(entity_type, entity_id);
