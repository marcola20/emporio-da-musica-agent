"""Runs the evaluation cases against the real model and writes a report for human review.

    python -m evals.run_evals                 # all cases
    python -m evals.run_evals --only id1,id2  # a subset

Each case is a short conversation with a pinned store clock. Simple deterministic checks
(which tools were called, facts that must or must not appear) flag likely problems; they
support, not replace, reading the conversations in evals/results/results.md.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

from emporio_agent import config
from emporio_agent.agent import Agent, AgentError, claims_unbacked_handoff
from emporio_agent.sessions import render_markdown

EVALS_DIR = Path(__file__).resolve().parent
CASES_FILE = EVALS_DIR / "cases.json"
RESULTS_DIR = EVALS_DIR / "results"

BRL_AMOUNT = re.compile(r"R\$\s?\d[\d.,]*\d|R\$\s?\d")
VALID_BRL = re.compile(r"R\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2})?")


def malformed_amounts(text: str) -> list[str]:
    """Amounts not in Brazilian format ("R$ 1.234,56" or "R$ 1.000"), e.g. "R$ 2,199,00" or "R$ 2199.00"."""
    return [amount for amount in BRL_AMOUNT.findall(text) if not VALID_BRL.fullmatch(amount)]

RATE_LIMIT_WAIT_SECONDS = 60
MAX_RATE_LIMIT_RETRIES = 5


def normalize(text: str) -> str:
    """Case-, accent-, punctuation- and spacing-insensitive form used by the checks.

    "R$ 2.199,00", "r$2.199,00" and "R$ 2.199,00" (non-breaking space) all become "r 2 199 00".
    """
    decomposed = unicodedata.normalize("NFKD", text.lower())
    no_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join("".join(c if c.isalnum() else " " for c in no_accents).split())


def _contains(haystack: str, needle: str) -> bool:
    # Pad with spaces so "br" does not match inside "obrigada", while "r 2 199 00" still matches.
    return f" {normalize(needle)} " in f" {haystack} "


def evaluate_checks(checks: dict, replies: list[str], tools_called: list[str]) -> list[str]:
    """Returns the list of failed checks (empty list = passed)."""
    text = normalize(" ".join(replies))
    failures = []
    if checks.get("no_tools") and tools_called:
        failures.append(f"expected no tool calls, got {tools_called}")
    for tool in checks.get("tools_called", []):
        if tool not in tools_called:
            failures.append(f"expected a call to {tool}")
    for tool in checks.get("tools_not_called", []):
        if tool in tools_called:
            failures.append(f"unexpected call to {tool}")
    for needle in checks.get("must_contain", []):
        if not _contains(text, needle):
            failures.append(f"missing {needle!r}")
    any_of = checks.get("must_contain_any", [])
    if any_of and not any(_contains(text, needle) for needle in any_of):
        failures.append(f"missing one of {any_of}")
    for needle in checks.get("must_not_contain", []):
        if _contains(text, needle):
            failures.append(f"should not contain {needle!r}")
    return failures


def reply_with_retry(agent: Agent, history: list[dict], message: str) -> str:
    """The free tier allows only a few requests per minute: wait and retry on 429."""
    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        try:
            return agent.reply(history, message)
        except AgentError as exc:
            if not exc.rate_limited or attempt == MAX_RATE_LIMIT_RETRIES:
                raise
            print(f"    rate limited, waiting {RATE_LIMIT_WAIT_SECONDS}s...", flush=True)
            time.sleep(RATE_LIMIT_WAIT_SECONDS)
    raise AssertionError("unreachable")


def run_case(agent: Agent, case: dict, default_datetime: str) -> dict:
    os.environ["STORE_REFERENCE_DATETIME"] = case.get("reference_datetime", default_datetime)
    history: list[dict] = []
    replies, error = [], None
    started = time.time()
    try:
        for message in case["messages"]:
            replies.append(reply_with_retry(agent, history, message))
    except AgentError as exc:
        error = str(exc)

    tools_called = [
        call["function"]["name"] for m in history if m["role"] == "assistant" for call in m.get("tool_calls", [])
    ]
    failures = [f"provider error: {error}"] if error else evaluate_checks(case.get("checks", {}), replies, tools_called)
    # Universal checks, for every case: never claim a handoff that did not happen, and never
    # garble an amount (the normalized checks above ignore punctuation, so they can't see it).
    if any(claims_unbacked_handoff(reply, history) for reply in replies):
        failures.append("claims a ticket/handoff without calling escalate_to_human")
    malformed = sorted({amount for reply in replies for amount in malformed_amounts(reply)})
    if malformed:
        failures.append(f"malformed BRL amounts: {malformed}")
    return {
        "id": case["id"],
        "description": case["description"],
        "expected": case["expected"],
        "reference_datetime": os.environ["STORE_REFERENCE_DATETIME"],
        "passed": not failures,
        "failures": failures,
        "tools_called": tools_called,
        "seconds": round(time.time() - started, 1),
        "history": history,
    }


def write_report(results: list[dict], model: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "results.json").write_text(
        json.dumps({"model": model, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    passed = sum(r["passed"] for r in results)
    lines = [
        "# Evaluation results",
        "",
        f"Model: `{model}` · Passed automatic checks: **{passed}/{len(results)}**",
        "",
        "Automatic checks are deterministic heuristics: read the conversations below too.",
        "",
        "| Case | Checks | Tools called | Notes |",
        "|---|---|---|---|",
    ]
    for r in results:
        status = "✅" if r["passed"] else "❌"
        lines.append(f"| [{r['id']}](#{r['id']}) | {status} | {', '.join(r['tools_called']) or '—'} | {'; '.join(r['failures'])} |")
    for r in results:
        lines += [
            "",
            "---",
            "",
            render_markdown(r["history"], title=r["id"]).replace(f"# {r['id']}", f"## {r['id']}", 1),
            f"*{r['description']}* Store clock: `{r['reference_datetime']}`.",
            "",
            f"**Expected:** {r['expected']}",
            "",
            f"**Automatic checks:** {'passed' if r['passed'] else 'failed: ' + '; '.join(r['failures'])}",
        ]
    report = RESULTS_DIR / "results.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.run_evals", description=__doc__.splitlines()[0])
    parser.add_argument("--only", help="comma-separated case ids to run")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    spec = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    cases = spec["cases"]
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in wanted]

    # Tickets opened during the evaluation go next to the report, not into conversations/.
    config.HANDOFF_FILE = RESULTS_DIR / "handoffs.jsonl"
    config.HANDOFF_FILE.unlink(missing_ok=True)
    agent = Agent()

    results = []
    for case in cases:
        print(f"- {case['id']} ...", end=" ", flush=True)
        result = run_case(agent, case, spec["default_reference_datetime"])
        results.append(result)
        print(("ok" if result["passed"] else "FAIL " + "; ".join(result["failures"])) + f" ({result['seconds']}s)")

    report = write_report(results, agent.model)
    print(f"\n{sum(r['passed'] for r in results)}/{len(results)} passed. Report: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
