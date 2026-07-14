"""Agentic LLM chat — an operator talks to the system through the model, which
reads the database and performs actions by calling *tools*.

Two engines are supported (the same ones the release-note drafter uses, selected
from the configuration page):

  * Claude — the Anthropic Messages API with native tool use.
  * Ollama — a local Ollama server (``/api/chat``) with function-calling.

The orchestration loop is identical for both: call the model, execute any tools
it requests (via the injected ``dispatch`` callback), feed the results back, and
repeat until the model answers with plain text. The tools themselves — what they
read/write in the database — live in :mod:`app.services.assistant`; this module
only knows how to talk to each engine and drive the loop.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

import httpx

from app.services.appconfig import LLMConfig

log = logging.getLogger("releaseit.llm.chat")

DEFAULT_CLAUDE_MODEL = "claude-opus-4-8"
DEFAULT_OLLAMA_MODEL = "llama3"

# Safety bound on the tool-use loop so a confused model can't call tools forever.
MAX_STEPS = 8
_MAX_TOKENS = 2048

SYSTEM_PROMPT = (
    "You are ReleaseIT's release-management assistant. You help operators inspect "
    "and drive the release lifecycle by calling the provided tools — never invent "
    "data or claim an action succeeded unless a tool confirmed it.\n\n"
    "Guidelines:\n"
    "- Always read the live system with the tools before answering; do not rely on "
    "memory of earlier turns for facts that may have changed.\n"
    "- To report project/release status, use `project_status_report` (optionally for "
    "one product). Summarise, for each running release: its current state, the actions "
    "already performed, and every blocker (open issues and missing required "
    "documents).\n"
    "- To create a release use `create_release`; to attach a document use "
    "`upload_document` (its content is the plain-text / Markdown body you provide).\n"
    "- The stored document is the single source of truth. After you generate, upload "
    "or create a document, NEVER reproduce, preview or summarise its body in your "
    "reply — the operator reads and downloads it from the document card shown in the "
    "chat. Reply only with a one-sentence confirmation that references the document by "
    "its title and type (e.g. \"Uploaded 'Release Notes v0.0.1' (Release Notes) as a "
    "draft — use the buttons below to download it.\").\n"
    "- Documents you generate/upload start as DRAFT. An operator approves a "
    "document with `approve_document` (do this only when they ask). When reporting "
    "documents, always include each one's approval status (DRAFT/APPROVED).\n"
    "- To let the operator download an existing document, call `get_document` — the "
    "interface shows Markdown and PDF download buttons for it; do not paste the file "
    "into your reply.\n"
    "- When moving a release between states with `transition_release`, attach the "
    "operator's comment as the `note`. If the operator has not already given a "
    "comment for the change in the conversation, ask them for one and wait for "
    "their reply before applying the transition — do not invent a note yourself.\n"
    "- Reference issues by their key and releases by product + version.\n"
    "- If a tool returns an error, explain it plainly and suggest how to resolve it. "
    "You act on behalf of the signed-in operator, so role or readiness restrictions "
    "reported by a tool are real and must be respected.\n"
    "- When the operator's request matches one of the predefined jobs described "
    "below, say explicitly which job you are running and describe each action as you "
    "perform it (see 'Predefined jobs').\n"
    "- Prefer concise, well-structured Markdown in your answers."
)


# --- Neutral tool + result types (shared with the assistant service) --------
@dataclass
class ToolSpec:
    """A tool the model may call. ``input_schema`` is a JSON Schema object; the
    ``handler`` is invoked by the dispatcher, not by the providers here."""
    name: str
    description: str
    input_schema: dict
    handler: Callable[[Any, dict], Any]


@dataclass
class ActionRecord:
    """One tool invocation, surfaced to the UI so the operator sees what the
    assistant did on their behalf. ``document`` carries an optional download
    reference (a document the tool surfaced) for the UI to render as a button."""
    tool: str
    ok: bool
    summary: str
    document: dict | None = None


@dataclass
class ChatResult:
    reply: str
    actions: list[ActionRecord] = field(default_factory=list)


# dispatch(name, args) -> (result_for_model, action_record)
Dispatch = Callable[[str, dict], "tuple[Any, ActionRecord]"]


class ChatService(Protocol):
    def run(
        self,
        *,
        system: str,
        history: list[dict],
        tools: list[ToolSpec],
        dispatch: Dispatch,
    ) -> ChatResult: ...


def _dump(obj: Any) -> str:
    """Serialise a tool result for the model (datetimes etc. -> str)."""
    return json.dumps(obj, default=str)


# --- Claude (Anthropic Messages API, native tool use) ----------------------
class ClaudeChatProvider:
    def __init__(self, api_key: str, model: str):
        self._api_key = api_key
        self._model = model or DEFAULT_CLAUDE_MODEL

    def run(self, *, system, history, tools, dispatch) -> ChatResult:
        import anthropic  # imported lazily so the dep is only needed when used

        client = anthropic.Anthropic(api_key=self._api_key)
        tool_defs = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in tools
        ]
        # History arrives as plain {role, content} turns; Claude accepts strings.
        messages: list[dict] = [
            {"role": m["role"], "content": m["content"]} for m in history
        ]
        actions: list[ActionRecord] = []
        # Accumulate the assistant's text across every step, not just the last one,
        # so the narration it emits before each tool call (announcing the job it is
        # running, "Syncing issues with label v0.0.1", ...) survives into the reply.
        texts: list[str] = []

        for _ in range(MAX_STEPS):
            msg = client.messages.create(
                model=self._model,
                max_tokens=_MAX_TOKENS,
                system=system,
                messages=messages,
                tools=tool_defs,
            )
            step_text = "".join(b.text for b in msg.content if b.type == "text").strip()
            if step_text:
                texts.append(step_text)
            tool_uses = [b for b in msg.content if b.type == "tool_use"]
            if not tool_uses:
                return ChatResult(reply="\n\n".join(texts), actions=actions)

            # Echo the assistant turn back verbatim, then answer every tool_use
            # with a matching tool_result block in one following user turn.
            messages.append(
                {"role": "assistant", "content": [_claude_block(b) for b in msg.content]}
            )
            results = []
            for tu in tool_uses:
                result, action = dispatch(tu.name, dict(tu.input or {}))
                actions.append(action)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": _dump(result),
                        "is_error": not action.ok,
                    }
                )
            messages.append({"role": "user", "content": results})

        return ChatResult(
            reply="\n\n".join(texts) or "I couldn't complete that within the allowed number of steps.",
            actions=actions,
        )


def _claude_block(block: Any) -> dict:
    """Re-serialise an Anthropic content block to a dict for the next request."""
    if block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    return {"type": "text", "text": block.text}


# --- Ollama (local server, OpenAI-style function calling) -------------------
class OllamaChatProvider:
    def __init__(self, base_url: str, model: str):
        self._base_url = base_url.rstrip("/")
        self._model = model or DEFAULT_OLLAMA_MODEL

    def run(self, *, system, history, tools, dispatch) -> ChatResult:
        tool_defs = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in tools
        ]
        messages: list[dict] = [{"role": "system", "content": system}]
        messages += [{"role": m["role"], "content": m["content"]} for m in history]
        actions: list[ActionRecord] = []
        # Keep every step's text (see the Claude provider) so job narration survives.
        texts: list[str] = []

        for _ in range(MAX_STEPS):
            resp = httpx.post(
                f"{self._base_url}/api/chat",
                json={
                    "model": self._model,
                    "messages": messages,
                    "tools": tool_defs,
                    "stream": False,
                },
                timeout=120,
            )
            resp.raise_for_status()
            msg = resp.json().get("message", {}) or {}
            step_text = (msg.get("content", "") or "").strip()
            if step_text:
                texts.append(step_text)
            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                return ChatResult(reply="\n\n".join(texts), actions=actions)

            messages.append(msg)
            for tc in tool_calls:
                fn = tc.get("function", {}) or {}
                name = fn.get("name", "")
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args or "{}")
                    except ValueError:
                        args = {}
                result, action = dispatch(name, dict(args))
                actions.append(action)
                messages.append({"role": "tool", "name": name, "content": _dump(result)})

        return ChatResult(
            reply="\n\n".join(texts) or "I couldn't complete that within the allowed number of steps.",
            actions=actions,
        )


def get_chat_service(cfg: LLMConfig) -> ChatService:
    """Resolve the configured engine for the assistant. Raises if the selected
    engine has no credentials/endpoint configured (there is no stub fallback)."""
    if cfg.provider == "claude" and cfg.claude_api_key:
        return ClaudeChatProvider(cfg.claude_api_key, cfg.claude_model)
    if cfg.provider == "ollama" and cfg.ollama_base_url:
        return OllamaChatProvider(cfg.ollama_base_url, cfg.ollama_model)
    raise RuntimeError(
        f"LLM provider '{cfg.provider}' is not configured "
        "(set a Claude API key or an Ollama base URL on the LLM engine page)."
    )
