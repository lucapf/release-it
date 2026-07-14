"""GitLab git hosting — repositories via the GitLab REST API (v4).

Talks to the configured GitLab instance (``git_gitlab_base_url``, the instance
root — e.g. ``https://gitlab.example.com``). The repository identifier is the
full project path (``group/project``), URL-encoded on every call.
"""
from __future__ import annotations

import logging
from urllib.parse import quote

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

log = logging.getLogger("releaseit.git.gitlab")


class GitLabGitProvider:
    def __init__(self, cfg: GitProviderConfig):
        self._cfg = cfg

    def _api(self, repo: str) -> str:
        base = self._cfg.base_url.rstrip("/")
        return f"{base}/api/v4/projects/{quote(repo, safe='')}"

    def _headers(self) -> dict:
        return {"PRIVATE-TOKEN": self._cfg.token}

    def _get(self, url: str, *, params: dict | None = None) -> httpx.Response:
        try:
            return httpx.get(url, headers=self._headers(), params=params, timeout=30)
        except httpx.HTTPError as exc:
            raise GitUnreachable(str(exc)) from exc

    def verify_repo(self, repo: str) -> None:
        resp = self._get(self._api(repo))
        if resp.status_code == 404:
            raise GitRepoNotFound(repo)
        self._raise_for_status(resp)

    def resolve_tag(self, repo: str, tag: str) -> str:
        resp = self._get(f"{self._api(repo)}/repository/tags/{quote(tag, safe='')}")
        if resp.status_code == 404:
            raise GitRefNotFound(f'tag "{tag}" not found in {repo}')
        self._raise_for_status(resp)
        return (resp.json().get("commit") or {}).get("id", "")

    def read_file_at_ref(self, repo: str, path: str, ref: str) -> str:
        resp = self._get(
            f"{self._api(repo)}/repository/files/{quote(path, safe='')}/raw",
            params={"ref": ref},
        )
        if resp.status_code == 404:
            raise GitFileNotFound(f'"{path}" not found in {repo}@{ref}')
        self._raise_for_status(resp)
        return resp.text

    def compare(self, repo: str, base_ref: str, head_ref: str) -> GitCompare:
        resp = self._get(
            f"{self._api(repo)}/repository/compare",
            params={"from": base_ref, "to": head_ref},
        )
        if resp.status_code == 404:
            raise GitRefNotFound(
                f'cannot compare "{base_ref}...{head_ref}" in {repo}: a ref does not exist'
            )
        self._raise_for_status(resp)
        data = resp.json()

        commits = [self._commit(repo, c) for c in data.get("commits", [])]
        total = len(commits)
        commits = commits[:MAX_COMMITS]

        files = []
        files_truncated = False
        for d in data.get("diffs", []) or []:
            withheld = bool(d.get("too_large") or d.get("collapsed"))
            patch, cut = cap_patch("" if withheld else (d.get("diff") or ""))
            if d.get("new_file"):
                status = "added"
            elif d.get("deleted_file"):
                status = "removed"
            elif d.get("renamed_file"):
                status = "renamed"
            else:
                status = "modified"
            # GitLab's compare diffs carry no per-file add/del counts; the
            # patch itself is the size signal.
            files.append(GitFileDiff(
                path=d.get("new_path") or d.get("old_path") or "",
                status=status,
                patch=patch,
                truncated=withheld or cut,
            ))
            files_truncated = files_truncated or withheld or cut

        web = f"{self._cfg.base_url.rstrip('/')}/{repo}/-/compare/{base_ref}...{head_ref}"
        return GitCompare(
            base_ref=base_ref,
            head_ref=head_ref,
            commits=commits,
            files=files,
            total_commits=total,
            commits_truncated=total > MAX_COMMITS,
            files_truncated=files_truncated,
            web_url=web,
        )

    def _commit(self, repo: str, c: dict) -> GitCommit:
        sha = c.get("id", "")
        message = c.get("message", "") or c.get("title", "") or ""
        return GitCommit(
            sha=sha,
            short_sha=c.get("short_id", sha[:8]),
            subject=c.get("title", "") or (message.splitlines()[0] if message else ""),
            message=cap_message(message),
            author=c.get("author_name", ""),
            authored_at=c.get("authored_date", "") or c.get("created_at", ""),
            url=f"{self._cfg.base_url.rstrip('/')}/{repo}/-/commit/{sha}",
        )

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        try:
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise GitUnreachable(str(exc)) from exc
