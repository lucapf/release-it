-- Simple single-repo products: the 'codebase' repository role.
--
-- A simple product keeps its whole codebase in one repository, tagged with the
-- product release version — no Helm umbrella chart. Change detection diffs that
-- repo directly between the two release tags.
--
-- 'deployment' and 'codebase' are the two ways a release's versions are
-- anchored to git, so a product has at most one repo of either role: the old
-- one-deployment index is widened into a one-anchor index.
ALTER TABLE product_git_repository
    DROP CONSTRAINT product_git_repository_role_check;
ALTER TABLE product_git_repository
    ADD CONSTRAINT product_git_repository_role_check
    CHECK (role IN ('component', 'library', 'deployment', 'codebase'));

DROP INDEX uq_pgr_one_deployment;
CREATE UNIQUE INDEX uq_pgr_one_anchor
    ON product_git_repository (product_id) WHERE role IN ('deployment', 'codebase');
