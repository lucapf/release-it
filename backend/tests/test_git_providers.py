"""The GitHub/GitLab git adapters: URLs, encoding, typed errors, truncation.

No network: httpx.get is faked. What matters is that each adapter asks its
hosting the right question and never turns "could not read it all" into a
clean-looking answer — withheld or oversized diffs must come back flagged.
"""
from __future__ import annotations

import pytest

from app.integrations.git import base as git_base
from app.integrations.git import github as gh_mod
from app.integrations.git import gitlab as gl_mod
from app.integrations.git import (
    GitFileNotFound,
    GitRefNotFound,
    GitRepoNotFound,
    GitHubGitProvider,
    GitLabGitProvider,
)
from app.services.appconfig import GitProviderConfig

GH = GitProviderConfig(enabled=True, base_url="https://api.github.com", token="t")
GL = GitProviderConfig(enabled=True, base_url="https://gitlab.example.com", token="t")


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", links=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text
        self.links = links or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("boom", request=None, response=None)


@pytest.fixture
def calls(monkeypatch):
    """Record every GET and answer from a scripted queue."""
    made: list[tuple[str, dict | None]] = []
    queue: list[FakeResponse] = []

    def fake_get(url, headers=None, params=None, timeout=None):
        made.append((url, params))
        return queue.pop(0) if queue else FakeResponse()

    import httpx
    monkeypatch.setattr(httpx, "get", fake_get)
    return made, queue


# --- GitHub ------------------------------------------------------------------
def test_github_missing_repo_is_a_typed_error(calls):
    made, queue = calls
    queue.append(FakeResponse(404))
    with pytest.raises(GitRepoNotFound):
        GitHubGitProvider(GH).verify_repo("acme/nope")
    assert made[0][0] == "https://api.github.com/repos/acme/nope"


def test_github_resolve_tag_peels_to_a_commit_sha(calls):
    made, queue = calls
    queue.append(FakeResponse(200, {"sha": "abc123"}))
    assert GitHubGitProvider(GH).resolve_tag("acme/app", "v1.0.0") == "abc123"
    assert made[0][0] == "https://api.github.com/repos/acme/app/commits/v1.0.0"


def test_github_missing_tag_is_a_typed_error(calls):
    _, queue = calls
    queue.append(FakeResponse(422))
    with pytest.raises(GitRefNotFound):
        GitHubGitProvider(GH).resolve_tag("acme/app", "v9.9.9")


def test_github_missing_file_is_a_typed_error(calls):
    _, queue = calls
    queue.append(FakeResponse(404))
    with pytest.raises(GitFileNotFound):
        GitHubGitProvider(GH).read_file_at_ref("acme/app", "Chart.yaml", "v1.0.0")


def test_github_compare_flags_withheld_patches_and_builds_the_web_url(calls):
    made, queue = calls
    queue.append(FakeResponse(200, {
        "total_commits": 1,
        "commits": [{
            "sha": "a" * 40,
            "commit": {"message": "Fix #1\n\nbody",
                       "author": {"name": "Ada", "date": "2026-01-01"}},
            "html_url": "https://github.com/acme/app/commit/aaa",
        }],
        "files": [
            {"filename": "app.py", "status": "modified", "additions": 1,
             "deletions": 1, "patch": "@@ -1 +1 @@"},
            # A large/binary file: GitHub sends no patch at all.
            {"filename": "big.bin", "status": "modified", "additions": 0,
             "deletions": 0},
        ],
    }))
    cmp = GitHubGitProvider(GH).compare("acme/app", "v1", "v2")
    assert made[0][0] == "https://api.github.com/repos/acme/app/compare/v1...v2"
    assert cmp.web_url == "https://github.com/acme/app/compare/v1...v2"
    assert cmp.commits[0].subject == "Fix #1"
    assert [f.truncated for f in cmp.files] == [False, True]
    assert not cmp.commits_truncated


def test_github_oversized_patch_is_capped_and_flagged(calls):
    _, queue = calls
    queue.append(FakeResponse(200, {
        "total_commits": 0, "commits": [],
        "files": [{"filename": "gen.py", "status": "modified", "additions": 9,
                   "deletions": 0, "patch": "x" * (git_base.MAX_PATCH_CHARS + 1)}],
    }))
    cmp = GitHubGitProvider(GH).compare("acme/app", "v1", "v2")
    assert len(cmp.files[0].patch) == git_base.MAX_PATCH_CHARS
    assert cmp.files[0].truncated


# --- GitLab ------------------------------------------------------------------
def test_gitlab_project_path_is_url_encoded(calls):
    made, queue = calls
    queue.append(FakeResponse(200, {}))
    GitLabGitProvider(GL).verify_repo("group/sub/project")
    assert made[0][0] == (
        "https://gitlab.example.com/api/v4/projects/group%2Fsub%2Fproject"
    )


def test_gitlab_resolve_tag_reads_the_commit_id(calls):
    made, queue = calls
    queue.append(FakeResponse(200, {"commit": {"id": "def456"}}))
    assert GitLabGitProvider(GL).resolve_tag("g/p", "v1.0.0") == "def456"
    assert made[0][0].endswith("/repository/tags/v1.0.0")


def test_gitlab_compare_maps_flags_and_statuses(calls):
    _, queue = calls
    queue.append(FakeResponse(200, {
        "commits": [{"id": "c" * 40, "short_id": "cccccccc", "title": "Add thing",
                     "message": "Add thing PROJ-5", "author_name": "Ada",
                     "authored_date": "2026-01-01"}],
        "diffs": [
            {"new_path": "new.py", "diff": "@@ +1 @@", "new_file": True},
            {"new_path": "huge.py", "diff": "", "too_large": True},
        ],
    }))
    cmp = GitLabGitProvider(GL).compare("g/p", "v1", "v2")
    assert cmp.web_url == "https://gitlab.example.com/g/p/-/compare/v1...v2"
    assert cmp.commits[0].url == "https://gitlab.example.com/g/p/-/commit/" + "c" * 40
    assert [f.status for f in cmp.files] == ["added", "modified"]
    assert [f.truncated for f in cmp.files] == [False, True]
    assert cmp.files_truncated
