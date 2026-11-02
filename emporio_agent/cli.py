"""Terminal chat with the agent: python -m emporio_agent [--session ID] [--verbose]."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import Callable

from . import config
from .agent import Agent, AgentError
from .sessions import load_session, new_session_id, save_session

EXIT_WORDS = {"sair", "exit", "quit", "tchau"}

WELCOME = (
    "Lia: Oi! Eu sou a Lia, assistente virtual da Empório da Música 🎸 "
    "Posso ajudar com instrumentos, preços, pedidos, trocas, horários e mais. Como posso ajudar?"
)


def _print_tool_calls(new_messages: list[dict]) -> None:
    for message in new_messages:
        for call in message.get("tool_calls", []):
            arguments = json.loads(call["function"]["arguments"] or "{}")
            print(f"   [tool] {call['function']['name']}({json.dumps(arguments, ensure_ascii=False)})")


def main(argv: list[str] | None = None, agent: Agent | None = None, read: Callable[[str], str] = input) -> int:
    parser = argparse.ArgumentParser(prog="python -m emporio_agent", description="Chat with Lia, the store's agent.")
    parser.add_argument("--session", help="resume a saved session by its id (see conversations/)")
    parser.add_argument("--verbose", action="store_true", help="show which tools the agent calls")
    args = parser.parse_args(argv)

    # Accents and emoji must print even on legacy Windows consoles or redirected output.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    try:
        agent = agent or Agent()
    except config.ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    if args.session:
        try:
            history = load_session(args.session)
        except (FileNotFoundError, ValueError) as exc:
            print(exc, file=sys.stderr)
            return 1
        session_id = args.session
        print(f"(sessão {session_id} retomada: {sum(m['role'] == 'user' for m in history)} mensagem(ns) anterior(es))")
    else:
        # Wall-clock time, not the pinned store clock: runs with the same pinned date
        # must not overwrite each other's sessions.
        history, session_id = [], new_session_id(datetime.now())

    print(f"(digite 'sair' para encerrar; sessão: {session_id})\n")
    print(WELCOME + "\n")

    while True:
        try:
            user_message = read("Você: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_message:
            continue
        if user_message.lower() in EXIT_WORDS:
            break

        turn_start = len(history)
        try:
            answer = agent.reply(history, user_message)
        except AgentError as exc:
            if exc.rate_limited:
                print("\n(O provedor do modelo limitou as requisições do free tier. Aguarde ~1 minuto e envie de novo.)\n")
            else:
                print(f"\n(Não consegui falar com o modelo agora: {exc}. Tente de novo.)\n")
            continue

        if args.verbose:
            _print_tool_calls(history[turn_start:])
        print(f"\nLia: {answer}\n")
        save_session(session_id, history, agent.model)  # after every turn, so nothing is lost on a crash

    if history:
        print(f"Conversa salva em {save_session(session_id, history, agent.model)}")
        print(f"Para continuar depois: python -m emporio_agent --session {session_id}")
    print("Lia: Obrigada pelo contato! Sua música começa aqui. 🎶")
    return 0
