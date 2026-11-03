"""Conversation persistence: one JSON file per session, plus a readable Markdown transcript.

The JSON keeps the full history (including tool calls and results) so a session can be
resumed exactly where it stopped, like a customer coming back to the same WhatsApp chat.
The Markdown transcript is what a human reads, and is how the examples in examples/ were made.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from . import config
from .agent import CORRECTION_PREFIX

SESSION_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")


def new_session_id(now: datetime) -> str:
    return f"{now:%Y%m%d-%H%M%S}"


def _path(session_id: str, suffix: str) -> Path:
    # Session ids come from the command line: only allow safe characters (no "../").
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise ValueError(f"Invalid session id: {session_id!r}")
    return config.CONVERSATIONS_DIR / f"{session_id}{suffix}"


def save_session(session_id: str, history: list[dict], model: str) -> Path:
    """Writes <id>.json (resumable) and <id>.md (readable). Returns the Markdown path."""
    json_path = _path(session_id, ".json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"session_id": session_id, "model": model, "history": history}
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    md_path = _path(session_id, ".md")
    md_path.write_text(render_markdown(history, title=f"Conversa {session_id}"), encoding="utf-8", newline="\n")
    return md_path


def load_session(session_id: str) -> list[dict]:
    json_path = _path(session_id, ".json")
    if not json_path.is_file():
        raise FileNotFoundError(f"Session not found: {json_path}")
    return json.loads(json_path.read_text(encoding="utf-8"))["history"]


def render_markdown(history: list[dict], title: str) -> str:
    """Customer and assistant messages, with each tool call and its raw result (collapsible)."""
    lines = [f"# {title}", ""]
    for message in history:
        role = message["role"]
        if role == "user":
            if message["content"].startswith(CORRECTION_PREFIX):
                lines += [
                    "> ⚙️ Automatic check, sent by the code (not the customer); the draft reply above "
                    f"was not shown to the customer: {message['content'][len(CORRECTION_PREFIX):].strip()}",
                    "",
                ]
            else:
                lines += [f"**Cliente:** {message['content']}", ""]
        elif role == "assistant":
            for call in message.get("tool_calls", []):
                function = call["function"]
                lines += [f"> 🔧 Tool call: `{function['name']}` `{function['arguments']}`", ""]
            if message.get("content"):
                lines += [f"**Lia:** {message['content'].strip()}", ""]
        elif role == "tool":
            lines += [
                "<details><summary>Tool result</summary>",
                "",
                "```json",
                json.dumps(json.loads(message["content"]), ensure_ascii=False, indent=2),
                "```",
                "",
                "</details>",
                "",
            ]
    return "\n".join(lines)
