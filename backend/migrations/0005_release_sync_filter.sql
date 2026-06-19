-- Saved tracker sync filter per release. Lets any operator persist the query
-- they use to retrieve the issue list so it is applied automatically next time
-- the release's Issues tab is opened.
CREATE TABLE release_sync_filter (
    release_id   BIGINT PRIMARY KEY REFERENCES release(id) ON DELETE CASCADE,
    filter_mode  TEXT        NOT NULL,            -- milestone | label | jql
    filter_value TEXT        NOT NULL DEFAULT '',
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
