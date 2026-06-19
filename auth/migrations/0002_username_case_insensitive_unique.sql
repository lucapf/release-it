-- Enforce case-insensitive username uniqueness at the data layer, matching the
-- application-level rule (login and duplicate detection compare lower(username)).
-- The original-case UNIQUE constraint from 0001 stays; this adds a functional
-- unique index so 'admin' and 'Admin' can never coexist even under a race.
CREATE UNIQUE INDEX app_user_username_lower_uniq ON app_user (lower(username));
