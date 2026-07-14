"""GitHub git hosting — repositories via the GitHub REST API.

Talks to the configured GitHub API (``git_github_base_url``). Compare payloads
are capped by GitHub itself (at most 250 commits and 300 files listed); the
adapter surfaces that as truncation flags rather than pretending the listing
is complete.
"""
from __future__ import annotations

import logging

import httpx

from app.integrations.git.base import (
    MAX_COMMITS,
    GitCommit,
    GitCompare,
    GitFileDiff,
    GitFileNotFound,
    GitRefNotFound,
    GitRepoNotFound,
    GitUnreachable,
    cap_message,
    cap_patch,
)
from app.services.appconfig import GitProviderConfig

log = logging.getLogger("releaseit.git.github")

# GitHub lists at most this many files in a compare response.
_GH_MAX_COMPARE_FILES = 300


def _web_base(api_base: str) -> str:
    """The hosting's web root for the configured API base — github.com for the
    public API, the instance root for GitHub Enterprise (`.../api/v3`)."""
    base = api_base.rstrip("/")
    if base == "https://api.github.com":
        return "https://github.com"
    return base.removesuffix("/api/v3")


class GitHubGitProvider:
    def __init__(self, cfg: GitProviderConfig):
        self._cfg = cfg

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._cfg.token}",
            "Accept": "application/vnd.github+json",
        }

    def _get(self, url: str, *, params: dict | None = None,
             headers: dict | None = None) -> httpx.Response:
        try:
            return httpx.get(url, headers=headers or self._headers(),
                             params=params, timeout=30)
        except httpx.HTTPError as exc:
            raise GitUnreachable(str(exc)) from exc

    def verify_repo(self, repo: str) -> None:
        resp = self._get(f"{self._cfg.base_url}/repos/{repo}")
        if resp.status_code == 404:
            raise GitRepoNotFound(repo)
        self._raise_for_status(resp)

    def resolve_tag(self, repo: str, tag: str) -> str:
        # /commits/{ref} peels annotated tags to their commit in one call.
        resp = self._get(f"{self._cfg.base_url}/repos/{repo}/commits/{tag}")
        if resp.status_code in (404, 422):
            raise GitRefNotFound(f'tag "{tag}" not found in {repo}')
        self._raise_for_status(resp)
        return resp.json().get("sha", "")

    def read_file_at_ref(self, repo: str, path: str, ref: str) -> str:
        resp = self._get(
            f"{self._cfg.base_url}/repos/{repo}/contents/{path}",
            params={"ref": ref},
            headers={**self._headers(), "Accept": "application/vnd.github.raw+json"},
        )
        if resp.status_code == 404:
            raise GitFileNotFound(f'"{path}" not found in {repo}@{ref}')
        self._raise_for_status(resp)
        return resp.text

    def compare(self, repo: str, base_ref: str, head_ref: str) -> GitCompare:
        url = f"{self._cfg.base_url}/repos/{repo}/compare/{base_ref}...{head_ref}"
        resp = self._get(url, params={"per_page": 100})
        if resp.status_code == 404:
            raise GitRefNotFound(
                f'cannot compare "{base_ref}...{head_ref}" in {repo}: a ref does not exist'
            )
        self._raise_for_status(resp)
        data = resp.json()

        commits = [self._commit(c) for c in data.get("commits", [])]
        total = int(data.get("total_commits", len(commits)))

        # The first page carries the files; further pages only add commits.
        next_url = resp.links.get("next", {}).get("url", "")
        while next_url and len(commits) < min(total, MAX_COMMITS):
            resp = self._get(next_url)
            self._raise_for_status(resp)
            commits.extend(self._commit(c) for c in resp.json().get("commits", []))
            next_url = resp.links.get("next", {}).get("url", "")
        commits = commits[:MAX_COMMITS]

        files = []
        for f in data.get("files", []) or []:
            patch, cut = cap_patch(f.get("patch") or "")
            files.append(GitFileDiff(
                path=f.get("filename", ""),
                status=f.get("status", "modified"),
                additions=int(f.get("additions", 0)),
                deletions=int(f.get("deletions", 0)),
                patch=patch,
                # No patch on a non-trivial file means GitHub withheld it
                # (too large / binary) — flag it so nothing reads as unchanged.
                truncated=cut or (not patch and f.get("status") != "renamed"),
            ))

        return GitCompare(
            base_ref=base_ref,
            head_ref=head_ref,
            commits=commits,
            files=files,
            total_commits=total,
            commits_truncated=len(commits) < total,
            files_truncated=len(files) >= _GH_MAX_COMPARE_FILES,
            web_url=f"{_web_base(self._cfg.base_url)}/{repo}/compare/{base_ref}...{head_ref}",
        )

    def _commit(self, c: dict) -> GitCommit:
        sha = c.get("sha", "")
        message = (c.get("commit") or {}).get("message", "") or ""
        author = ((c.get("commit") or {}).get("author") or {})
        return GitCommit(
            sha=sha,
            short_sha=sha[:8],
            subject=message.splitlines()[0] if message else "",
            message=cap_message(message),
            author=author.get("name", "") or (c.get("author") or {}).get("login", ""),
            authored_at=author.get("date", ""),
            url=c.get("html_url", "") or "",
        )

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        try:
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise GitUnreachable(str(exc)) from exc
