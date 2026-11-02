"""Tests for session persistence and the CLI loop, with a fake agent (no network)."""

import json

import pytest

from emporio_agent import config
from emporio_agent.agent import AgentError
from emporio_agent.cli import main
from emporio_agent.sessions import load_session, render_markdown, save_session

HISTORY = [
    {"role": "user", "content": "Quanto custa o Takamine GD20?"},
    {
        "role": "assistant",
        "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "search_products", "arguments": '{"query": "GD20"}'}}
        ],
    },
    {"role": "tool", "tool_call_id": "c1", "content": '{"results": [{"price": "R$ 2.199,00"}]}'},
    {"role": "assistant", "content": "Ele custa R$ 2.199,00."},
]


@pytest.fixture(autouse=True)
def conversations_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONVERSATIONS_DIR", tmp_path)
    monkeypatch.setenv("STORE_REFERENCE_DATETIME", "2026-03-25T14:00")
    return tmp_path


class FakeAgent:
    model = "fake-model"

    def __init__(self, fail_with=None):
        self.fail_with = fail_with

    def reply(self, history, message):
        if self.fail_with:
            raise self.fail_with
        history += [{"role": "user", "content": message}, {"role": "assistant", "content": f"eco: {message}"}]
        return f"eco: {message}"


def scripted_input(*lines):
    remaining = list(lines)

    def read(prompt):
        if not remaining:
            raise EOFError
        return remaining.pop(0)

    return read


# --- sessions -------------------------------------------------------------------


def test_session_round_trip(conversations_dir):
    save_session("abc-1", HISTORY, "fake-model")
    assert load_session("abc-1") == HISTORY
    saved = json.loads((conversations_dir / "abc-1.json").read_text(encoding="utf-8"))
    assert saved["model"] == "fake-model"


@pytest.mark.parametrize("bad_id", ["../secrets", "a/b", "", "x" * 65])
def test_session_id_cannot_escape_the_folder(bad_id):
    with pytest.raises(ValueError):
        load_session(bad_id)


def test_missing_session():
    with pytest.raises(FileNotFoundError):
        load_session("does-not-exist")


def test_markdown_shows_messages_and_tool_calls():
    md = render_markdown(HISTORY, title="Teste")
    assert md.startswith("# Teste")
    assert "**Cliente:** Quanto custa o Takamine GD20?" in md
    assert "`search_products`" in md and '"price": "R$ 2.199,00"' in md
    assert md.index("search_products") < md.index("**Lia:** Ele custa R$ 2.199,00.")


# --- CLI ------------------------------------------------------------------------


def test_cli_chats_saves_and_exits(conversations_dir, capsys):
    code = main([], agent=FakeAgent(), read=scripted_input("oi", "", "sair"))
    out = capsys.readouterr().out
    assert code == 0
    assert "Lia: eco: oi" in out
    [saved] = conversations_dir.glob("*.json")
    assert saved.with_suffix(".md").is_file()
    assert f"--session {saved.stem}" in out
    assert load_session(saved.stem)[-1]["content"] == "eco: oi"


def test_cli_resumes_a_session(conversations_dir, capsys):
    save_session("old", [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}], "fake-model")
    main(["--session", "old"], agent=FakeAgent(), read=scripted_input("de novo"))
    assert [m["content"] for m in load_session("old")] == ["a", "b", "de novo", "eco: de novo"]
    assert "retomada" in capsys.readouterr().out


def test_cli_unknown_session_fails_cleanly(capsys):
    assert main(["--session", "nope"], agent=FakeAgent(), read=scripted_input()) == 1


def test_cli_survives_rate_limit(capsys):
    agent = FakeAgent(fail_with=AgentError("429", rate_limited=True))
    assert main([], agent=agent, read=scripted_input("oi")) == 0
    assert "limitou as requisições" in capsys.readouterr().out


def test_cli_reports_missing_api_key(monkeypatch, capsys):
    monkeypatch.setenv("LLM_API_KEY", "")
    assert main([], read=scripted_input()) == 1
    assert "LLM_API_KEY" in capsys.readouterr().err
