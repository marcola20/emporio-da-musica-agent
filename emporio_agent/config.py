"""Project paths, environment configuration and the store clock."""

from __future__ import annotations

import os
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
