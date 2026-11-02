"""Tests for the prompt and the tool-calling loop, using a scripted fake LLM (no network)."""

import json
from datetime import datetime
from types import SimpleNamespace

import openai
import pytest
from openai.types.chat import ChatCompletionMessage

from emporio_agent import config
from emporio_agent.agent import FALLBACK_REPLY, MAX_MODEL_CALLS, Agent, AgentError
from emporio_agent.prompts import build_system_prompt, store_hours_status


class FakeLLM:
    """Mimics client.chat.completions.create, returning scripted assistant messages in order."""

    def __init__(self, *messages):
        self.script = list(messages)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(choices=[SimpleNamespace(message=item)])


def text(content):
    return ChatCompletionMessage(role="assistant", content=content)


def tool_call(name, arguments, call_id="call_1"):
    return ChatCompletionMessage.model_validate(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}
            ],
        }
    )


@pytest.fixture(autouse=True)
def pinned_clock(monkeypatch):
    monkeypatch.setenv("STORE_REFERENCE_DATETIME", "2026-03-25T14:00")


# --- prompt -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (datetime(2026, 3, 25, 14, 0), "ABERTA agora (hoje fecha às 18:00)"),  # Wednesday
        (datetime(2026, 3, 25, 7, 30), "FECHADA agora. Reabre hoje (25/03) às 09:00"),
        (datetime(2026, 3, 27, 19, 0), "FECHADA agora. Reabre amanhã (28/03) às 09:00"),  # Friday night
        (datetime(2026, 3, 28, 12, 59), "ABERTA agora (hoje fecha às 13:00)"),  # Saturday
        (datetime(2026, 3, 28, 13, 0), "FECHADA agora. Reabre segunda-feira (30/03) às 09:00"),
        (datetime(2026, 3, 29, 10, 0), "FECHADA agora. Reabre amanhã (30/03) às 09:00"),  # Sunday
    ],
)
def test_store_hours_status(moment, expected):
    assert expected in store_hours_status(moment)


def test_system_prompt_has_persona_policies_and_clock():
    prompt = build_system_prompt(config.now())
    assert "Lia" in prompt
    assert "Direito de Arrependimento" in prompt  # full manual is inlined
    assert prompt.rstrip().endswith("Feriados não estão no sistema.")  # clock last (cache-friendly)
    assert "quarta-feira, 25/03/2026 14:00" in prompt


# --- loop ---------------------------------------------------------------------


def test_plain_answer_without_tools():
    llm = FakeLLM(text("Oi! Como posso ajudar?"))
    history = []
    assert Agent(client=llm, model="fake").reply(history, "oi") == "Oi! Como posso ajudar?"
    assert [m["role"] for m in history] == ["user", "assistant"]
    sent = llm.requests[0]
    assert sent["messages"][0]["role"] == "system" and sent["messages"][1:] == history[:1]
    assert {t["function"]["name"] for t in sent["tools"]} >= {"search_products", "get_order_status"}


def test_tool_call_is_executed_and_result_sent_back():
    llm = FakeLLM(tool_call("search_products", {"query": "Takamine GD20"}), text("Custa R$ 2.199,00."))
    history = []
    answer = Agent(client=llm, model="fake").reply(history, "Quanto custa o Takamine GD20?")

    assert answer == "Custa R$ 2.199,00."
    assert [m["role"] for m in history] == ["user", "assistant", "tool", "assistant"]
    tool_message = history[2]
    assert tool_message["tool_call_id"] == "call_1"
    assert json.loads(tool_message["content"])["results"][0]["price"] == "R$ 2.199,00"
    assert llm.requests[1]["messages"][-1] == tool_message  # second call sees the tool result
    json.dumps(history)  # history stays serializable for persistence


def test_history_is_kept_across_turns():
    llm = FakeLLM(text("Oi!"), text("Claro."))
    agent, history = Agent(client=llm, model="fake"), []
    agent.reply(history, "oi")
    agent.reply(history, "tudo bem?")
    assert [m["content"] for m in llm.requests[1]["messages"][1:]] == ["oi", "Oi!", "tudo bem?"]


def test_provider_error_rolls_back_the_turn():
    llm = FakeLLM(text("Oi!"), openai.OpenAIError("connection failed"))
    agent, history = Agent(client=llm, model="fake"), []
    agent.reply(history, "oi")
    with pytest.raises(AgentError):
        agent.reply(history, "quanto custa?")
    assert [m["content"] for m in history] == ["oi", "Oi!"]


def test_loop_stops_after_max_calls():
    llm = FakeLLM(*[tool_call("search_products", {"query": "violão"}) for _ in range(MAX_MODEL_CALLS)])
    history = []
    assert Agent(client=llm, model="fake").reply(history, "?") == FALLBACK_REPLY
    assert len(llm.requests) == MAX_MODEL_CALLS


def test_empty_model_answer_falls_back():
    assert Agent(client=FakeLLM(text("")), model="fake").reply([], "oi") == FALLBACK_REPLY


def test_missing_api_key_gives_clear_error(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "")
    with pytest.raises(config.ConfigError, match="LLM_API_KEY"):
        Agent()
