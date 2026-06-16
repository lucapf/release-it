"""Pipeline execution integrations (version 2 feature).

On a state change (e.g. -> Approved) ReleaseIT can trigger a pipeline on a
configured service via REST + token auth. Each runner implements ``trigger``.
GitLab CI and Ansible/AWX are stubbed: when their integration is disabled they
log the intended call instead of performing it, so the workflow is exercisable
end-to-end without external systems.
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
            log.info("[stub] GitLab CI trigger release=%s ref=%s", release_id, ref)
            return {"runner": self.name, "stubbed": True, "release_id": release_id}
        resp = httpx.post(
            f"{settings.gitlab_base_url}/trigger/pipeline",
            headers={"PRIVATE-TOKEN": settings.gitlab_token},
            json={"ref": ref, "variables": variables},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()


class AWXRunner:
    name = "awx"

    def trigger(self, release_id: int, ref: str, variables: dict[str, str]) -> dict:
        if not settings.awx_enabled:
            log.info("[stub] AWX job launch release=%s ref=%s", release_id, ref)
            return {"runner": self.name, "stubbed": True, "release_id": release_id}
        resp = httpx.post(
            f"{settings.awx_base_url}/api/v2/job_templates/launch/",
            headers={"Authorization": f"Bearer {settings.awx_token}"},
            json={"extra_vars": variables},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()


_RUNNERS: dict[str, PipelineRunner] = {
    GitLabCIRunner.name: GitLabCIRunner(),
    AWXRunner.name: AWXRunner(),
}


def get_runner(name: str = "gitlab-ci") -> PipelineRunner:
    if name not in _RUNNERS:
        raise ValueError(f"Unknown pipeline runner '{name}'")
    return _RUNNERS[name]
