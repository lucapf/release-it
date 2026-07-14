-- Git repositories linked to a product.
--
-- A product's code lives in one or more git repositories, each linked here with
-- a role:
--   * 'deployment' — the Helm umbrella chart (app-of-apps) repository. It is
--     tagged with the product release version, and its Chart.yaml dependencies
--     list every service name + version. At most one per product.
--   * 'component'  — one service's source repository. component_name is the
--     dependency name the service appears under in the umbrella Chart.yaml —
--     that name is the join key change detection uses, so it is unique per
--     product.
--   * 'library'    — linked for reference/browsing only (no change detection).
--
-- (The 'codebase' role for single-repo products arrives in migration 0018.)
--
-- tag_pattern renders a version into the repo's tag name ("v{version}" ->
-- "v1.2.0"). chart_path is where the umbrella Chart.yaml lives inside the
-- deployment repo; ignored for other roles.
--
-- Provider credentials are global app_config keys (like the issue tracker's) —
-- only the repository binding is per-product.
CREATE TABLE product_git_repository (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id     BIGINT NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    provider       TEXT   NOT NULL CHECK (provider IN ('github', 'gitlab')),
    -- GitHub "owner/repo"; GitLab "group/project" path.
    repo           TEXT   NOT NULL,
    role           TEXT   NOT NULL CHECK (role IN ('component', 'library', 'deployment')),
    component_name TEXT   NOT NULL DEFAULT '',
    tag_pattern    TEXT   NOT NULL DEFAULT 'v{version}',
    web_url        TEXT   NOT NULL DEFAULT '',
    chart_path     TEXT   NOT NULL DEFAULT 'Chart.yaml',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (role <> 'component' OR component_name <> ''),
    UNIQUE (product_id, repo)
);

CREATE UNIQUE INDEX uq_pgr_one_deployment
    ON product_git_repository (product_id) WHERE role = 'deployment';
CREATE UNIQUE INDEX uq_pgr_component_name
    ON product_git_repository (product_id, component_name) WHERE role = 'component';
CREATE INDEX idx_pgr_product ON product_git_repository (product_id);

-- The AI code review lands as a versioned release document of this type.
-- Deliberately 'manual': 'generated' would let the assistant's generic
-- prompt-driven document job produce a diff-less lookalike — the dedicated
-- review service is the only writer.
INSERT INTO document_type (name, kind, generation_prompt)
VALUES ('Code Review Report', 'manual', '')
ON CONFLICT (name) DO NOTHING;
