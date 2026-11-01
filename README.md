# Empório da Música — Customer Support Agent

> 🚧 Work in progress. This README is a skeleton and will be completed as the project evolves.

A Python prototype of a text-message customer-support agent for **Empório da Música**, a (fictional) musical instrument store in Campo Grande/MS, Brazil. The agent answers customers in Portuguese, looks up live data (products, prices, stock, promotions, order status) through tools, and follows the store's policy manual.

## Quickstart

Requirements: Python 3.10+ and a free Google Gemini API key ([get one here](https://aistudio.google.com/apikey)).

```bash
git clone <repo-url>
cd <repo-folder>
python -m venv .venv
```

Activate the virtual environment:

```bash
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# Linux / macOS
source .venv/bin/activate
```

Install dependencies and configure your key:

```bash
pip install -r requirements.txt
cp .env.example .env   # then edit .env and set LLM_API_KEY
```

Run the agent:

```bash
python -m emporio_agent
```

Run the tests:

```bash
python -m pytest
```

## Architecture

_TODO_

## Technical decisions

_TODO: framework, LLM/provider, retrieval architecture, prompt strategy, data handling, persistence, interface._

## Assumptions

_TODO_

## Conversation examples

_TODO: see [`examples/`](examples/)._

## Known limitations and future work

_TODO_

## Use of AI coding assistants

_TODO: summary of [`docs/ai_workflow.md`](docs/ai_workflow.md)._
