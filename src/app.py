"""Command-line entry point.

    python -m src.app ingest                          # build the vector store from data/
    python -m src.app ask "How do I roll back payments-api?"     # plain RAG answer
    python -m src.app agent "What's pending on the hotfix checklist?"  # agent picks a tool
    python -m src.app chat                            # interactive agent loop
"""

import argparse
import sys

from src.agent import AgentResult, run_agent
from src.ingest import build_index
from src.rag import Answer, ask


def print_answer(answer: Answer) -> None:
    print(answer.text)
    print("\nSources: " + ", ".join(answer.sources))


def print_agent_result(result: AgentResult) -> None:
    for call in result.tool_calls:
        args = ", ".join(f"{k}={v!r}" for k, v in call.input.items())
        print(f"  -> {call.name}({args}){'  [error]' if call.is_error else ''}")
    print()
    print(result.text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="releasewise", description="Release & ops assistant")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ingest", help="(re)build the vector store from data/")
    ask_p = sub.add_parser("ask", help="answer one question with plain RAG")
    ask_p.add_argument("question")
    agent_p = sub.add_parser("agent", help="let the agent choose a tool for one request")
    agent_p.add_argument("question")
    sub.add_parser("chat", help="interactive agent loop")
    args = parser.parse_args(argv)

    if args.command == "ingest":
        n = build_index()
        print(f"Indexed {n} chunks.")
    elif args.command == "ask":
        print_answer(ask(args.question))
    elif args.command == "agent":
        print_agent_result(run_agent(args.question))
    elif args.command == "chat":
        print("ReleaseWise — ask a question or ask to run a checklist (Ctrl+D to quit)")
        while True:
            try:
                question = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if question:
                print_agent_result(run_agent(question))
    return 0


if __name__ == "__main__":
    sys.exit(main())
