-- The tracker owns whether an issue is finished.
--
-- Release-It used to decide this itself, by matching an issue's status *name*
-- against a comma-separated CLOSED_BUG_STATUSES setting (default "Done"). That
-- was a second definition of a fact the tracker already owns, and it diverged:
-- a Jira project whose done-status is called "Resolved" or "Shipped" had every
-- issue counted as open forever, so the `no_open_issues` readiness guard could
-- never be satisfied and the release could never be approved.
--
-- Each provider now reports its own verdict (Jira: the status' statusCategory;
-- GitHub/GitLab: the issue state) and we cache it alongside the status name.

ALTER TABLE jira_issue ADD COLUMN closed BOOLEAN NOT NULL DEFAULT false;

-- Backfill from the old rule so existing caches are not all marked open on
-- upgrade. This is the last time that rule is applied: the next sync of each
-- release overwrites these values with the tracker's own answer.
UPDATE jira_issue SET closed = true WHERE lower(status) = 'done';
