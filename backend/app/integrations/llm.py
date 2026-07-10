"""LLM release-note generation — pluggable, selected by runtime configuration.

Two engines are supported, switchable from the configuration page:
  * Claude — the Anthropic Messages API (official ``anthropic`` SDK).
  * Ollama — a local Ollama server (``/api/generate``).

There is no stub: if the selected engine isn't configured (no Claude API key /
no Ollama URL), release-note generation reports a configuration error.
"""
from __future__ import annotations

import logging
from typing import Protocol

import httpx

from app.services.appconfig import LLMConfig

log = logging.getLogger("releaseit.llm")

DEFAULT_CLAUDE_MODEL = "claude-opus-4-8"
DEFAULT_OLLAMA_MODEL = "llama3"

_SYSTEM = (
    "You are a release manager assistant. Write concise, well-structured "
    "Markdown release notes grouped into '## Features' and '## Bug Fixes' "
    "sections. Reference each issue by its key. Do not invent issues."
)


class LLMReleaseNoteService(Protocol):
    def draft_release_notes(self, version: str, issues: list[dict]) -> str: ...


def _prompt(version: str, issues: list[dict]) -> str:
    lines = [f"Write release notes for version {version}.", "", "Issues:"]
    if issues:
        for i in issues:
            lines.append(
                f"- {i.get('key', '')} [{i.get('type', '')}] "
                f"{i.get('summary', '')} (status: {i.get('status', '')})"
            )
    else:
        lines.append("- (no issues found for this release)")
    return "\n".join(lines)


# --- Claude (Anthropic Messages API) ---------------------------------------
class ClaudeProvider:
    def __init__(self, api_key: str, model: str):
        self._api_key = api_key
        self._model = model or DEFAULT_CLAUDE_MODEL

    def draft_release_notes(self, version: str, issues: list[dict]) -> str:
        import anthropic  # imported lazily so the dep is only needed when used

        client = anthropic.Anthropic(api_key=self._api_key)
        message = client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=_SYSTEM,
            messages=[{"role": "user", "content": _prompt(version, issues)}],
        )
        return "".join(b.text for b in message.content if b.type == "text")


# --- Ollama (local server) -------------------------------------------------
class OllamaProvider:
    def __init__(self, base_url: str, model: str):
        self._base_url = base_url.rstrip("/")
        self._model = model or DEFAULT_OLLAMA_MODEL

    def draft_release_notes(self, version: str, issues: list[dict]) -> str:
        resp = httpx.post(
            f"{self._base_url}/api/generate",
            json={
                "model": self._model,
                "system": _SYSTEM,
                "prompt": _prompt(version, issues),
                "stream": False,
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json().get("response", "")


def get_release_note_service(cfg: LLMConfig) -> LLMReleaseNoteService:
    """Resolve the configured engine. Raises if the selected engine has no
    credentials/endpoint configured (there is no stub fallback)."""
    if cfg.provider == "claude" and cfg.claude_api_key:
        return ClaudeProvider(cfg.claude_api_key, cfg.claude_model)
    if cfg.provider == "ollama" and cfg.ollama_base_url:
        return OllamaProvider(cfg.ollama_base_url, cfg.ollama_model)
    raise RuntimeError(
        f"LLM provider '{cfg.provider}' is not configured "
        "(set a Claude API key or an Ollama base URL)."
    )
