-- The tracker's web page for a cached issue (Jira: <base>/browse/REL-1;
-- GitHub: the issue's html_url), so operators can open it in the ticketing
-- system straight from the release's Issues tab.
--
-- Existing rows keep '' until their release is next synced; the UI hides the
-- "open in tracker" action for issues whose url is still unknown.
ALTER TABLE jira_issue ADD COLUMN url TEXT NOT NULL DEFAULT '';
