"""LLM assistant: the agentic tool-use loop and the tool dispatcher.

No real model or database is involved — the Anthropic client is faked to script a
tool call followed by a text answer, and the dispatcher is exercised with a fake
tool + connection so we can assert its savepoint/error handling directly.
"""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import app.integrations.llm_chat as llm_chat
from app.core.identity import Principal
from app.integrations.llm_chat import ActionRecord, ClaudeChatProvider, ToolSpec
from app.services import assistant, release_ops


# --- Fake Anthropic client scripting a tool_use then a final text answer ----
def _text(t):
    return SimpleNamespace(type="text", text=t)


def _tool_use(id, name, input):
    return SimpleNamespace(type="tool_use", id=id, name=name, input=input)


class _FakeMessages:
    def __init__(self, script):
        self._script = list(script)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=self._script.pop(0))


class _FakeAnthropic:
    def __init__(self, messages):
        self.messages = messages

    def __call__(self, api_key):  # anthropic.Anthropic(api_key=...)
        return self


def test_claude_loop_runs_tools_then_returns_text(monkeypatch):
    # Turn 1: the model asks to call list_products. Turn 2: it answers in text.
    fake_messages = _FakeMessages(
        [
            [_text("let me look"), _tool_use("t1", "list_products", {})],
            [_text("Here are the products.")],
        ]
    )
    monkeypatch.setattr(
        "anthropic.Anthropic", _FakeAnthropic(fake_messages), raising=False
    )

    calls = []

    def dispatch(name, args):
        calls.append((name, args))
        return [{"id": 1, "name": "Widget"}], ActionRecord(name, True, "Listed products")

    tools = [ToolSpec("list_products", "list", {"type": "object"}, handler=lambda c, a: None)]
    provider = ClaudeChatProvider(api_key="k", model="claude-test")
    result = provider.run(
        system="sys",
        history=[{"role": "user", "content": "what products exist?"}],
        tools=tools,
        dispatch=dispatch,
    )

    # The reply keeps the narration from BEFORE the tool call ("let me look")
    # joined with the final answer — so job announcements/step narration survive.
    assert result.reply == "let me look\n\nHere are the products."
    assert calls == [("list_products", {})]
    assert [a.tool for a in result.actions] == ["list_products"]
    # The tool result was fed back: the second model call carries the tool_result.
    second_call_messages = fake_messages.calls[1]["messages"]
    assert any(
        isinstance(m["content"], list)
        and any(b.get("type") == "tool_result" for b in m["content"])
        for m in second_call_messages
    )


def test_claude_loop_stops_at_step_budget(monkeypatch):
    # A model that always asks for a tool must not loop forever.
    always_tool = [[_text(""), _tool_use(f"t{i}", "noop", {})] for i in range(llm_chat.MAX_STEPS + 3)]
    fake_messages = _FakeMessages(always_tool)
    monkeypatch.setattr("anthropic.Anthropic", _FakeAnthropic(fake_messages), raising=False)

    tools = [ToolSpec("noop", "noop", {"type": "object"}, handler=lambda c, a: None)]
    provider = ClaudeChatProvider(api_key="k", model="claude-test")
    result = provider.run(
        system="sys",
        history=[{"role": "user", "content": "go"}],
        tools=tools,
        dispatch=lambda n, a: ({}, ActionRecord(n, True, "noop")),
    )
    assert len(fake_messages.calls) == llm_chat.MAX_STEPS
    assert "couldn't complete" in result.reply


# --- Dispatcher: savepoint + error handling ---------------------------------
class _FakeConn:
    def __init__(self):
        self.entered = 0
        self.rolled_back = 0

    @contextmanager
    def transaction(self):
        self.entered += 1
        try:
            yield self
        except Exception:
            self.rolled_back += 1
            raise  # psycopg's transaction() re-raises after rolling back the savepoint


def _ctx(conn):
    return assistant.ToolContext(
        conn=conn, principal=Principal("op", set()), sm=None, cfg=None
    )


def _dispatcher_with(monkeypatch, spec, conn):
    monkeypatch.setattr(assistant, "build_tools", lambda: [spec])
    dispatch, _tools = assistant.make_dispatcher(_ctx(conn))
    return dispatch


def test_dispatch_success_commits_savepoint(monkeypatch):
    conn = _FakeConn()
    spec = ToolSpec("echo", "echo", {"type": "object"},
                    handler=lambda c, a: {"echoed": a.get("x")})
    dispatch = _dispatcher_with(monkeypatch, spec, conn)

    result, action = dispatch("echo", {"x": 5})
    assert result == {"echoed": 5}
    assert action.ok is True
    assert conn.entered == 1 and conn.rolled_back == 0


def test_dispatch_release_action_error_is_reported(monkeypatch):
    conn = _FakeConn()

    def boom(c, a):
        raise release_ops.ReleaseActionError(409, "guard blocked it")

    spec = ToolSpec("act", "act", {"type": "object"}, handler=boom)
    dispatch = _dispatcher_with(monkeypatch, spec, conn)

    result, action = dispatch("act", {})
    assert action.ok is False
    assert action.summary == "guard blocked it"
    assert result == {"error": "guard blocked it"}
    # The savepoint was rolled back, keeping the outer transaction usable.
    assert conn.rolled_back == 1


# --- Capabilities: the "Assistant actions" page + LLM-engine prompts --------
def test_describe_actions_covers_every_tool_and_flags_writes():
    described = {a["name"]: a for a in assistant.describe_actions()}
    # One entry per registered tool, never drifting from the live registry.
    assert set(described) == {t.name for t in assistant.build_tools()}
    for a in described.values():
        assert a["description"]
        assert a["kind"] in {"read", "action"}
    # Tools that change the system are flagged as actions; pure reads are not.
    assert described["create_release"]["kind"] == "action"
    assert described["upload_document"]["kind"] == "action"
    assert described["transition_release"]["kind"] == "action"
    assert described["set_release_criteria"]["kind"] == "action"
    # Reading a release's issues asks the ticketing system — it changes nothing here.
    assert described["list_release_issues"]["kind"] == "read"
    assert described["search_issues"]["kind"] == "read"
    assert described["get_release_status"]["kind"] == "read"
    assert described["list_products"]["kind"] == "read"


def test_prompt_templates_cover_the_three_assistant_jobs():
    prompts = {p["key"]: p for p in assistant.PROMPT_TEMPLATES}
    assert set(prompts) == {"generate_document", "release_status", "advance_workflow"}
    for p in prompts.values():
        assert p["title"] and p["description"] and p["prompt"]
    # The generate-document job is generic: it verifies the type, then uploads.
    gen = prompts["generate_document"]["prompt"].lower()
    assert "upload" in gen
    assert "document type" in gen
    # It gates on the type being supported and automatic before generating.
    assert "get_generation_prompt" in prompts["generate_document"]["prompt"]
    assert "manual" in gen
    # The workflow prompt drives the configured workflow.
    assert "workflow" in prompts["advance_workflow"]["prompt"].lower()


def test_job_playbook_lists_jobs_and_teaches_matching_and_narration():
    playbook = assistant.render_job_playbook(assistant.effective_prompts())
    # Every predefined job appears by its title, with its steps.
    for p in assistant.PROMPT_TEMPLATES:
        assert p["title"] in playbook
    # It teaches cross-language / loose-intent matching (the Italian example) ...
    assert "Italian" in playbook and "release notes" in playbook.lower()
    # ... announcing the job explicitly, and narrating each concrete action.
    assert "which job you are running" in playbook
    assert "label v0.0.1" in playbook  # example of describing the actions performed


def test_job_playbook_tracks_admin_overrides():
    playbook = assistant.render_job_playbook(
        assistant.effective_prompts({"generate_document": {"title": "Craft the notes"}})
    )
    assert "Craft the notes" in playbook


def test_effective_prompts_apply_overrides_and_ignore_blanks():
    # No overrides → the built-in defaults, unchanged.
    assert assistant.effective_prompts() == assistant.PROMPT_TEMPLATES
    assert assistant.effective_prompts({}) == assistant.PROMPT_TEMPLATES

    merged = {p["key"]: p for p in assistant.effective_prompts(
        {
            "release_status": {"prompt": "Custom status prompt", "title": "  "},
            "unknown_key": {"prompt": "ignored"},
        }
    )}
    # The overridden field wins; a blank field falls back to the default; and an
    # unknown key is ignored (the shape always matches the defaults).
    assert merged["release_status"]["prompt"] == "Custom status prompt"
    default_title = next(p["title"] for p in assistant.PROMPT_TEMPLATES if p["key"] == "release_status")
    assert merged["release_status"]["title"] == default_title
    assert set(merged) == {p["key"] for p in assistant.PROMPT_TEMPLATES}


def test_prompt_override_for_only_keeps_fields_that_differ():
    default = next(p for p in assistant.PROMPT_TEMPLATES if p["key"] == "generate_document")
    # A value equal to the default (or blank) stores nothing → tracks the default.
    assert assistant.prompt_override_for("generate_document", dict(default)) == {}
    assert assistant.prompt_override_for("generate_document", {"prompt": "   "}) == {}
    # Only the changed field is retained.
    assert assistant.prompt_override_for(
        "generate_document", {"title": "New title", "prompt": default["prompt"]}
    ) == {"title": "New title"}
    # An unknown key yields no override.
    assert assistant.prompt_override_for("nope", {"title": "x"}) == {}


# --- Document generation gate (get_generation_prompt) -----------------------
def _doc_type(name, kind, generation_prompt=""):
    return {"name": name, "kind": kind, "generation_prompt": generation_prompt}


def test_list_document_types_flags_generation_mode(monkeypatch):
    monkeypatch.setattr(assistant.config_repo, "list_document_types",
                        lambda conn: [_doc_type("Release Notes", "generated", "..."),
                                      _doc_type("Contract", "manual")])
    out = assistant._list_document_types(_ctx(object()), {})
    assert out == [
        {"name": "Contract", "generation": "manual"},
        {"name": "Release Notes", "generation": "automatic"},
    ]


def test_get_generation_prompt_returns_prompt_for_automatic_type(monkeypatch):
    monkeypatch.setattr(assistant.config_repo, "get_document_type_by_name",
                        lambda conn, name: _doc_type("Release Notes", "generated", "Draft the notes."))
    out = assistant._get_generation_prompt(_ctx(object()), {"doc_type": "release notes"})
    assert out == {"doc_type": "Release Notes", "generation": "automatic",
                   "generation_prompt": "Draft the notes."}


def test_get_generation_prompt_errors_when_type_unsupported(monkeypatch):
    monkeypatch.setattr(assistant.config_repo, "get_document_type_by_name",
                        lambda conn, name: None)
    monkeypatch.setattr(assistant.config_repo, "document_type_names",
                        lambda conn: {"Contract"})
    try:
        assistant._get_generation_prompt(_ctx(object()), {"doc_type": "Foo"})
        assert False, "expected an error for an unsupported type"
    except release_ops.ReleaseActionError as exc:
        assert exc.status_code == 404
        assert "not supported" in exc.detail and "Contract" in exc.detail


def test_get_generation_prompt_errors_when_type_is_manual(monkeypatch):
    monkeypatch.setattr(assistant.config_repo, "get_document_type_by_name",
                        lambda conn, name: _doc_type("Contract", "manual"))
    try:
        assistant._get_generation_prompt(_ctx(object()), {"doc_type": "Contract"})
        assert False, "expected an error for a manual type"
    except release_ops.ReleaseActionError as exc:
        assert exc.status_code == 400
        assert "manual generation" in exc.detail


def test_get_generation_prompt_errors_when_automatic_type_has_no_prompt(monkeypatch):
    monkeypatch.setattr(assistant.config_repo, "get_document_type_by_name",
                        lambda conn, name: _doc_type("Release Notes", "generated", "   "))
    try:
        assistant._get_generation_prompt(_ctx(object()), {"doc_type": "Release Notes"})
        assert False, "expected an error when no prompt is configured"
    except release_ops.ReleaseActionError as exc:
        assert exc.status_code == 400
        assert "no generation prompt" in exc.detail


def test_dispatch_unknown_tool(monkeypatch):
    conn = _FakeConn()
    spec = ToolSpec("known", "known", {"type": "object"}, handler=lambda c, a: None)
    dispatch = _dispatcher_with(monkeypatch, spec, conn)

    result, action = dispatch("does_not_exist", {})
    assert action.ok is False
    assert "Unknown tool" in action.summary
    assert conn.entered == 0  # never opened a savepoint for an unknown tool
