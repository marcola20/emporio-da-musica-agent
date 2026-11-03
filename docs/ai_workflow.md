# AI-assisted workflow log

This file records, phase by phase, how I (Marcos) used **Claude Code** (Anthropic's coding agent, model Claude Opus 5.5) while building this project: what I asked for, what the assistant proposed, and what I approved or changed. It feeds the "Use of AI coding assistants" section of the README.

**Working agreement set up front:** the work is split into phases (exploration → architecture → setup → data/tools → agent → interface → evaluation → examples → README → delivery). The assistant stops at the end of each phase, summarizes, and waits for my approval; it explains the *why* of each decision (I must be able to defend every choice in interviews); it shows each commit message before committing; it never commits secrets; and the simplest robust solution wins over a sophisticated one.

---

## Phase 0 — Exploration

- **I asked:** read the challenge and the store's material before writing any code; profile every CSV (types, nulls, duplicates, inconsistencies, relationships) and summarize the policy manual (size in tokens, topics, rules about identity verification, returns, hours, payment); list the ambiguities we need to decide.
- **The assistant did:** extracted both PDFs, profiled the six CSVs with a throwaway script (kept outside the repo), and cross-checked foreign keys, order totals vs. prices, status vs. stock, and duplicated customer identifiers.
- **Key findings:** clean encoding and keys, but several semantic inconsistencies (e.g. a `coming_soon` product with past sales, two order totals that don't match current prices, a duplicated customer e-mail, empty product categories, stale open orders, contradictory phone numbers in the manual). The manual is ~4–5k tokens and has **no rule about verifying identity** before sharing order data.
- **I approved** the report and the proposed assumptions (e.g. require order number + phone/e-mail to disclose an order; status overrides stock; always report the stored order total).

## Phase 1 — Architecture proposal

- **I asked:** 2–3 options with trade-offs for each decision (agent approach, model/provider, framework, interface, persistence, data handling), a recommendation, and a folder structure — justified by the problem, not by the job description.
- **The assistant proposed:** a hybrid of the full policy manual in the system prompt (no RAG: it is small and questions often cross sections) plus function calling for live, sensitive data; access control and arithmetic enforced in Python, not in the prompt; a hand-written tool-calling loop instead of LangChain/LangGraph (one loop, four tools — a framework would hide what matters); a CLI; JSON-file session persistence; stdlib-only data handling; the OpenAI-compatible Chat Completions API so the provider is just configuration, with Gemini's free tier as default. Groq was ruled out because its free-tier tokens-per-minute limit is smaller than our prompt.
- **I approved** the architecture and chose Gemini by providing a free API key.

## Phase 2 — Setup

- **The assistant did:** created the virtual environment, pinned direct dependencies, and smoke-tested the key and tool calling against Gemini's OpenAI-compatible endpoint before writing project code.
- **What the smoke test changed:** the model initially planned (`gemini-2.5-flash`) returned 404 (retired), and the `gemini-flash-latest` alias took ~1 min per call; `gemini-3.5-flash` answered a tool-calling round trip in ~1 s, so it became the pinned default (`gemini-3.5-flash-lite` noted as a fallback).
- **Also decided:** keep the challenge PDF out of the public repo (`.gitignore`); `.gitattributes` keeps `data/` byte-identical and normalizes line endings across OSes.
- **I approved** the five setup commits and asked the assistant to create the public GitHub repository and push.

## Phase 3 — Data layer and tools

- **I asked:** load and clean the data, implement the agent's tools with clear docstrings (they become the tool descriptions for the LLM), type hints, error handling and simple pytest tests.
- **The assistant did:**
  - Transcribed the policy PDF by hand into `data/policies.md` (automatic extraction scrambled the tables), keeping the wording and marking each contradiction it resolved with a visible "Nota de curadoria".
  - `data.py`: stdlib-only loading into frozen dataclasses; cleaning rules in code (originals untouched): status overrides stock, only active promotions are joined, phones reduced to digits, payment/status codes mapped to Portuguese labels, recorded order totals kept as-is.
  - `tools.py`: four tools — `search_products` (accent-, case-, spacing- and typo-tolerant matching with a crude Portuguese singularizer; price filters on the price actually paid), `get_product_details` (PIX price and interest-free installments computed from policy 3.1), `get_order_status` (identity check: order number + matching phone/e-mail, with the same error for "wrong contact" and "no such order" to prevent enumeration; never returns contact data; day counts for the return policies), `escalate_to_human` (JSONL ticket + protocol number). A dispatcher `run_tool` turns any bad call into an `{"error": ...}` result instead of crashing.
  - Principle made explicit: **arithmetic in code, judgment in the LLM** (e.g. the tool returns "36 days since delivery"; the model compares it with the 7-day rule in the policy, which stays the single source of truth for return windows).
  - 54 pytest tests (no LLM calls), all passing; they encode the edge cases found in Phase 0.
- **Fixed during review of its own smoke run:** "R$ 1.000,00" passed as a string was parsed as 1.0; the category enum was duplicated in code and is now built from `categories.csv`.
- **I approved** the commits and the push.

## Phase 4 — Agent

- **I asked:** a system prompt with the store's persona, a clear strategy for when to use each tool, guardrails (never invent prices/stock/status, no cross-customer data, follow the policies, polite out-of-scope refusals, basic prompt-injection resistance, human handoff) and conversation history as decided in Phase 1.
- **The assistant did:**
  - `prompts.py`: persona "Lia" in Portuguese, tool-use rules per type of question, six non-negotiable rules, the full manual inside `<manual>` tags, and the clock at the very end (stable prefix first, so the provider's prompt caching can reuse it). Opening/closing status is computed in code (`store_hours_status`), consistent with "arithmetic in code".
  - `agent.py`: an explicit tool-calling loop (~40 lines) with a cap of 6 model calls per message, history as JSON-serializable dicts (ready to persist), rollback of the turn on provider errors, and rate-limit detection. Assistant messages are stored with `model_dump` so Gemini's thought signatures survive multi-step tool calls.
  - `tests/test_agent.py`: the loop is tested with a scripted fake LLM (no network), plus opening-hours edge cases.
- **Smoke test with the real model** (8 scenarios: catalog under R$1000, address, price + expired promotion, regret/return with identity check, another customer's order, accessories, off-topic, prompt injection, complaint on a Sunday night): all behaved as intended. Two fixes came out of it: the model computed a PIX price by itself (correct, but against the "arithmetic in code" rule), so `search_products` now returns `pix_price`; and the lite model listed only some of the results and used Markdown bold, so the prompt was tightened.
- **A finding that changed a decision:** the error body showed that the free tier of `gemini-3.5-flash` allows only **20 requests per day** — not enough for one evaluation run, nor for an evaluator. The assistant ran the same scenarios on `gemini-3.5-flash-lite`: all correct, faster (1–3 s), slightly less thorough. It laid out the options (free lite model vs. flash with billing).
- **I chose** `gemini-3.5-flash-lite` as the default, so the evaluator can run everything for free and the committed examples reflect exactly what they will run; `gemini-3.5-flash` is documented as a one-line upgrade.
- **I approved** the commits and the push.

## Phase 5 — Interface

- **I asked:** implement the interface chosen in Phase 1 (CLI), simple and functional.
- **The assistant did:**
  - `cli.py` / `__main__.py`: `python -m emporio_agent` opens a terminal chat; `--verbose` prints each tool call; `--session <id>` resumes a saved conversation; `sair`, Ctrl+C or Ctrl+D end it. Provider errors and free-tier rate limits produce a friendly message and the user can just resend (the agent already rolled the turn back). stdout is reconfigured to UTF-8 so accents and emoji print on any Windows console.
  - `sessions.py`: each session is saved after every turn as JSON (full history, resumable) and as a Markdown transcript that shows tool calls with their raw results in collapsible blocks — the format that will back the examples in Phase 7. Session ids are validated, so `--session ../x` cannot read or write outside `conversations/`.
  - `tests/test_cli.py`: persistence round trip, path-traversal rejection, Markdown rendering and the CLI loop with a fake agent and scripted input.
- **Found in the end-to-end run with the real model:** session ids were derived from the pinned store clock, so two runs with the same `STORE_REFERENCE_DATETIME` would overwrite each other — they now use the wall clock. Resuming a session worked with context ("o mais barato *deles*").
- **Found when I tried it myself:** running `python -m emporio_agent` in a terminal without the virtual environment active crashed with `ModuleNotFoundError: dotenv`. An evaluator could easily do the same, so the entry point now catches it and prints how to activate the venv (or call `.venv\Scripts\python` directly), and the README explains the PowerShell execution-policy workaround.
- **I approved** the commits and the push, then tried the agent by hand with a test script the assistant suggested (catalog, policies, orders with real customer data, returns with a pinned date, guardrails, session resume).

## Phase 6 — Evaluation

- **I asked:** a set of test questions (the four challenge scenarios plus edge cases: unknown product, unknown order, another customer's order, expired promotion, out-of-scope, prompt injection, data + policy) and a simple script that runs them and saves the answers for us to review; then fix what fails.
- **The assistant proposed and built:** `evals/cases.json` with 20 short conversations, each with a pinned store clock, the expected behavior in plain words and a few deterministic checks (tools called / not called, facts that must or must not appear, normalized for case, accents and punctuation). `evals/run_evals.py` runs them against the real model, waits and retries on free-tier 429s, and writes a Markdown report with every conversation. An LLM-as-judge was deliberately not used: with 20 cases, reading them is cheap and more reliable.
- **Run 1 (baseline): 18/20 on the checks — but reading the conversations found a worse problem the checks missed.** Twice the agent *said* it had opened a ticket (once inventing a protocol number, "#2026-0329-01") without calling `escalate_to_human`; one of those cases even passed the checks. In production that leaves a customer waiting for a call that never comes.
- **Fix in two layers, following the project's "guarantee it in code" rule:** a prompt rule (a ticket exists only after the tool, with exactly its protocol), and a code check in the agent loop: if a reply claims a handoff ("abri", "encaminhei", "protocolo nº…") and `escalate_to_human` never ran in the conversation, the agent sends the model one automatic correction asking it to really escalate or rephrase. The note stays in the history, marked as automatic, so transcripts show it. The same check became a universal eval check.
- **Run 2: 19/20.** The guardrail fired live and turned a fake ticket into a real one (`EMP-20260329-2C7B38`). The only failure was the check's wording ("dentro *desse* prazo"), widened. Reading the answers also revealed "R$ 2,199,00": the model had re-typed a correct tool value wrongly — invisible to the normalized checks. Fixed with a prompt rule (copy amounts verbatim) and a universal eval check for malformed BRL amounts, which flagged that run retroactively.
- **Run 3 (final): 20/20**, all conversations reviewed by hand. The code guardrail fired again (a draft invented "#2026-0207-7" and was corrected into a real ticket), which shows the prompt rule alone is not enough for the lite model. Baseline and final reports are both committed (`evals/results/run1_baseline.md`, `evals/results/results.md`).
