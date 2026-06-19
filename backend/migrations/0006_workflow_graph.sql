-- Database-backed release workflow graph.
--
-- The release state machine lives in the database so administrators can edit
-- the whole graph at runtime (configuration page). This migration creates the
-- tables and seeds the standard workflow; the export endpoint
-- (GET /api/v1/workflow/export) renders the current graph back as YAML.
--
-- A state's ordinal `score` defines workflow ordering; the lowest-scored state
-- is the initial state. A state with no transitions is final.
CREATE TABLE workflow_state (
    name  TEXT    PRIMARY KEY,
    score INTEGER NOT NULL UNIQUE
);

-- Named transitions out of a state. `target` is the destination state (validated
-- in the application layer on write — no FK so the whole graph can be replaced
-- in any order). `roles` lists who may perform it (empty = fall back to
-- settings.default_transition_roles); `requires` lists readiness guards that
-- must hold first (e.g. no_open_issues, docs_complete, checks_done). `position`
-- preserves the authored ordering within a state.
CREATE TABLE workflow_transition (
    state    TEXT    NOT NULL REFERENCES workflow_state(name) ON DELETE CASCADE,
    name     TEXT    NOT NULL,
    target   TEXT    NOT NULL,
    roles    TEXT[]  NOT NULL DEFAULT '{}',
    requires TEXT[]  NOT NULL DEFAULT '{}',
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (state, name)
);

-- Seed the standard release workflow:
--   Draft --Ready--> In QA --Approve--> Approved   (Approve guarded)
--         --Cancel-> Cancelled         --Reject---> Rejected
INSERT INTO workflow_state (name, score) VALUES
    ('Draft',     0),
    ('In QA',     1),
    ('Cancelled', 2),
    ('Rejected',  3),
    ('Approved',  4);

INSERT INTO workflow_transition (state, name, target, roles, requires, position) VALUES
    ('Draft', 'Ready',   'In QA',     ARRAY['Developer','Release Manager','Administrator'], ARRAY[]::TEXT[],                          0),
    ('Draft', 'Cancel',  'Cancelled', ARRAY['Developer','Release Manager','Administrator'], ARRAY[]::TEXT[],                          1),
    ('In QA', 'Approve', 'Approved',  ARRAY['QA Manager','Release Manager','Administrator'], ARRAY['no_open_issues','docs_complete'], 0),
    ('In QA', 'Reject',  'Rejected',  ARRAY['QA Manager','Release Manager','Administrator'], ARRAY[]::TEXT[],                          1);
