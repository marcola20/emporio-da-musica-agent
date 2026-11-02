"""Project paths, environment configuration and the store clock."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

# Paths are resolved from this file, so the project works from any working directory
# and in folders whose names contain spaces or accents.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
POLICIES_FILE = DATA_DIR / "policies.md"
CONVERSATIONS_DIR = PROJECT_ROOT / "conversations"
HANDOFF_FILE = CONVERSATIONS_DIR / "handoffs.jsonl"

load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_MODEL = "gemini-3.5-flash-lite"


class ConfigError(RuntimeError):
    """Raised when required configuration (e.g. the API key) is missing."""


@dataclass(frozen=True)
class LLMSettings:
    api_key: str
    base_url: str
    model: str


def llm_settings() -> LLMSettings:
    """LLM provider settings from the environment / .env (see .env.example)."""
    api_key = os.getenv("LLM_API_KEY", "").strip()
    if not api_key or api_key == "your-api-key-here":
        raise ConfigError(
            "LLM_API_KEY is not set. Copy .env.example to .env and add your API key "
            "(a free Gemini key: https://aistudio.google.com/apikey)."
        )
    return LLMSettings(
        api_key=api_key,
        base_url=os.getenv("LLM_BASE_URL", "").strip() or DEFAULT_BASE_URL,
        model=os.getenv("LLM_MODEL", "").strip() or DEFAULT_MODEL,
    )

# Campo Grande/MS is UTC-4 all year (Brazil abolished daylight saving time in 2019).
# A fixed offset avoids depending on the IANA tz database, which Windows does not ship
# (zoneinfo would need the extra "tzdata" package there).
STORE_TZ = timezone(timedelta(hours=-4), "America/Campo_Grande")


def now() -> datetime:
    """Current date and time at the store.

    STORE_REFERENCE_DATETIME (e.g. "2026-03-25" or "2026-03-25T14:30") pins the clock so runs
    are reproducible. A date without a time means 10:00, when the store is open.
    """
    pinned = os.getenv("STORE_REFERENCE_DATETIME", "").strip()
    if not pinned:
        return datetime.now(STORE_TZ)
    parsed = datetime.fromisoformat(pinned)
    if "T" not in pinned and " " not in pinned:
        parsed = datetime.combine(parsed.date(), time(10, 0))
    return parsed.replace(tzinfo=STORE_TZ)
