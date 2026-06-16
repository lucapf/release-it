-- Jira issues fetched for a release via the Jira integration (stub by default).
-- A sync replaces the stored set for the release, so it always reflects the
-- last query (release label or custom JQL) the user ran.
CREATE TABLE jira_issue (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    release_id  BIGINT      NOT NULL REFERENCES release(id) ON DELETE CASCADE,
    issue_key   TEXT        NOT NULL,                       -- e.g. REL-1
    issue_type  TEXT        NOT NULL DEFAULT 'Task',        -- Story | Bug | Task | ...
    summary     TEXT        NOT NULL DEFAULT '',
    status      TEXT        NOT NULL DEFAULT '',            -- e.g. Done, In Progress
    synced_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (release_id, issue_key)
);

CREATE INDEX idx_jira_issue_release ON jira_issue(release_id);
