-- Checks management (per-release pre/post checklists + the global default
-- check templates) and environments are removed from the product. Their tables
-- are dropped, and the `checks_done` readiness guard the checklists backed is
-- stripped from any workflow transitions that still declare it.

DROP TABLE IF EXISTS check_item CASCADE;
DROP TABLE IF EXISTS check_template CASCADE;
DROP TABLE IF EXISTS environment CASCADE;

UPDATE workflow_transition
   SET requires = array_remove(requires, 'checks_done');
