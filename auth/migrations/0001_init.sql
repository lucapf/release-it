-- releaseit-auth schema: users, roles, and their assignment.
-- This DB is independent from the ReleaseIT backend database.

CREATE TABLE role (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE
);

CREATE TABLE app_user (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    email         TEXT,
    password_hash TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE user_role (
    user_id BIGINT NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    role_id BIGINT NOT NULL REFERENCES role(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, role_id)
);

-- The four ReleaseIT roles.
INSERT INTO role (name) VALUES
    ('Developer'), ('Release Manager'), ('QA Manager'), ('Administrator');
