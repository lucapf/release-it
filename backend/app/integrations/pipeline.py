"""Pipeline execution integrations (version 2 feature).

On a state change (e.g. -> Approved) ReleaseIT can trigger a pipeline on a
configured service via REST + token auth. Each runner implements ``trigger``.
The runner calls its real backing service; there is no stub, so ``trigger``
raises when its integration is not enabled.
"""
from __future__ import annotations

import logging
from typing import Protocol

import httpx

from app.core.config import settings

log = logging.getLogger("releaseit.pipeline")


class PipelineRunner(Protocol):
    name: str

    def trigger(self, release_id: int, ref: str, variables: dict[str, str]) -> dict: ...


class GitLabCIRunner:
    name = "gitlab-ci"

    def trigger(self, release_id: int, ref: str, variables: dict[str, str]) -> dict:
        if not settings.gitlab_enabled:
            raise RuntimeError("GitLab CI integration is not enabled")
        resp = httpx.post(
            f"{settings.gitlab_base_url}/trigger/pipeline",
            headers={"PRIVATE-TOKEN": settings.gitlab_token},
            json={"ref": ref, "variables": variables},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()


_RUNNERS: dict[str, PipelineRunner] = {
    GitLabCIRunner.name: GitLabCIRunner(),
}


def get_runner(name: str = "gitlab-ci") -> PipelineRunner:
    if name not in _RUNNERS:
        raise ValueError(f"Unknown pipeline runner '{name}'")
    return _RUNNERS[name]
