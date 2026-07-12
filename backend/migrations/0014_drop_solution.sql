-- Drop the Solution entity: it is not part of the current release.
--
-- Products no longer belong to a solution, so the FK column goes with the table.
-- Audit rows with entity_type = 'solution' are left in place: the audit log is an
-- append-only historical record and entity_type is free-text, not a FK.
ALTER TABLE product DROP COLUMN IF EXISTS solution_id;
DROP TABLE IF EXISTS solution;
