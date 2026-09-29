"""Command-line entry point.

    python -m src.app ingest                 # build the vector store from data/
    python -m src.app ask "How do I roll back payments-api?"
    python -m src.app chat                   # interactive Q&A loop
"""

import argparse
import sys

from src.ingest import build_index
from src.rag import Answer, ask


def print_answer(answer: Answer) -> None:
    print(answer.text)
    print("\nSources: " + ", ".join(answer.sources))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="releasewise", description="Release & ops assistant")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ingest", help="(re)build the vector store from data/")
    ask_p = sub.add_parser("ask", help="ask a single question")
    ask_p.add_argument("question")
    sub.add_parser("chat", help="interactive question loop")
    args = parser.parse_args(argv)

    if args.command == "ingest":
        n = build_index()
        print(f"Indexed {n} chunks.")
    elif args.command == "ask":
        print_answer(ask(args.question))
    elif args.command == "chat":
        print("ReleaseWise — ask a release/ops question (Ctrl+D to quit)")
        while True:
            try:
                question = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if question:
                print_answer(ask(question))
    return 0


if __name__ == "__main__":
    sys.exit(main())
