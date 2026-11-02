"""The agent: a plain tool-calling loop over an OpenAI-compatible Chat Completions API.

One user message may need several model calls: the model asks for tools, we run them and
send the results back, until it answers in text. That loop is all an "agent framework"
would do here, so it is written out explicitly (~40 lines) instead of hidden in a library.
"""

from __future__ import annotations

import logging

import openai

from . import config
from .prompts import build_system_prompt
from .tools import get_tool_schemas, run_tool

logger = logging.getLogger(__name__)

# Upper bound of model calls per user message, so a confused model cannot loop forever.
MAX_MODEL_CALLS = 6

FALLBACK_REPLY = (
    "Desculpe, não consegui concluir sua solicitação agora. Se preferir, posso encaminhar "
    "seu caso para um atendente humano. 🙏"
)


class AgentError(RuntimeError):
    """The LLM provider could not be reached or returned an error (shown to the user politely)."""

    def __init__(self, message: str, rate_limited: bool = False):
        super().__init__(message)
        # Free tiers allow only a few requests per minute; callers can wait and retry.
        self.rate_limited = rate_limited


class Agent:
    def __init__(self, client: openai.OpenAI | None = None, model: str | None = None):
        if client is None:
            settings = config.llm_settings()
            # The SDK already retries rate limits (429) and server errors with backoff.
            client = openai.OpenAI(api_key=settings.api_key, base_url=settings.base_url, timeout=60, max_retries=3)
            model = model or settings.model
        self.client = client
        self.model = model or config.DEFAULT_MODEL
        self.tools = get_tool_schemas()

    def reply(self, history: list[dict], user_message: str) -> str:
        """Answers one customer message, appending every message of the turn to `history`.

        `history` is the conversation as plain, JSON-serializable dicts (user, assistant and
        tool messages), so it can be saved and resumed. The system prompt is not stored in it:
        it is rebuilt on every call so the clock is always current. If the provider fails,
        the history is rolled back to how it was, so the user can simply retry.
        """
        turn_start = len(history)
        history.append({"role": "user", "content": user_message})
        try:
            for _ in range(MAX_MODEL_CALLS):
                messages = [{"role": "system", "content": build_system_prompt(config.now())}, *history]
                response = self.client.chat.completions.create(model=self.model, messages=messages, tools=self.tools)
                message = response.choices[0].message
                # model_dump keeps provider-specific fields (e.g. Gemini's thought signatures on
                # tool calls) that must be sent back unchanged in the next request.
                history.append(message.model_dump(exclude_none=True))

                if not message.tool_calls:
                    return (message.content or "").strip() or FALLBACK_REPLY

                for call in message.tool_calls:
                    logger.info("tool call: %s(%s)", call.function.name, call.function.arguments)
                    result = run_tool(call.function.name, call.function.arguments)
                    logger.debug("tool result: %s", result)
                    history.append({"role": "tool", "tool_call_id": call.id, "content": result})
        except openai.OpenAIError as exc:
            del history[turn_start:]
            raise AgentError(str(exc), rate_limited=isinstance(exc, openai.RateLimitError)) from exc

        logger.warning("Gave up after %d model calls", MAX_MODEL_CALLS)
        history.append({"role": "assistant", "content": FALLBACK_REPLY})
        return FALLBACK_REPLY
