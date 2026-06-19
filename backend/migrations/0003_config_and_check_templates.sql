-- Runtime configuration store and default check templates.
--
-- app_config is a simple key/value store for settings that are editable at
-- runtime via the configuration page (issue-tracker selection + credentials).
-- Values override the env-var defaults baked into the image; an absent key
-- falls back to the corresponding setting in app.core.config.
CREATE TABLE app_config (
    key        TEXT        PRIMARY KEY,
    value      TEXT        NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Global default checks: applied to every newly created release so each
-- release starts with the organisation's standard pre/post checklist.
CREATE TABLE check_template (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    label      TEXT        NOT NULL,
    phase      TEXT        NOT NULL CHECK (phase IN ('pre', 'post')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
