-- Documentation has been unified into the versioned `document` feature (uploads
-- only — no online authoring). The old free-text `documentation` table and the
-- `docs_complete` readiness guard it backed are removed; document requirements
-- are now expressed with the per-type `document:<TypeName>` workflow guards.

DROP TABLE IF EXISTS documentation CASCADE;

-- Strip the now-removed docs_complete guard from any existing transitions (it
-- is seeded by 0006 on the In QA -> Approve transition).
UPDATE workflow_transition
   SET requires = array_remove(requires, 'docs_complete');
