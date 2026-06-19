-- Per-product issue-tracker project.
--
-- The remote project an issue tracker points at (e.g. the GitHub repository
-- "owner/repo", or a Jira project key) is a property of the *product*, not a
-- global setting: different products live in different repositories. This moves
-- that binding onto the product row. The global github_repo config key is no
-- longer used.
ALTER TABLE product ADD COLUMN tracker_repo TEXT NOT NULL DEFAULT '';
