-- The ticketing system is the only source of truth for a release's issues.
--
-- `jira_issue` was a cache: a sync (manual, or the 10-minute scheduler) wrote the
-- tracker's answer into it and everything else read the rows back. A cache of a
-- fact someone else owns is a second, lagging copy of that fact, and it behaved
-- like one — the issue list, the readiness gate and the status page could each be
-- looking at a different moment in the tracker's history, and a release could be
-- approved on a bug that had already been reopened. The transition gate had grown
-- a synchronous re-sync to work around exactly that.
--
-- Every read now queries the tracker directly, so there is nothing to cache and
-- nothing to keep in step. What Release-It *does* own — and what it now stores in
-- place of the rows — is the search criteria that says which tickets belong to
-- the release (e.g. label = v0.0.1), chosen when the release is created.
DROP TABLE IF EXISTS jira_issue;

-- The criteria outlive the sync they were named after: this table is no longer a
-- "sync filter" but the definition of a release's contents.
ALTER TABLE release_sync_filter RENAME TO release_issue_filter;

-- The scheduled sync is gone with the cache it existed to refresh.
DELETE FROM app_config WHERE key = 'sync_interval_minutes';
