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
