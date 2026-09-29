"""The agent's tools: plain Python functions + a JSON schema Claude reads to decide when to call them.

Claude never runs code itself. It reads each tool's name/description/schema, and when it
wants one it replies with a `tool_use` block (tool name + arguments). Our loop in agent.py
runs the matching function below and sends the result back.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from src import config
from src.retriever import retrieve

CHECKLIST_DIR = config.DATA_DIR / "checklists"
CHECKBOX = re.compile(r"^\s*[-*]\s+\[( |x|X)\]\s+(.+)$")


# ---------- search_docs ----------

def search_docs(query: str) -> str:
    """RAG retrieval as a tool: return the relevant chunks, tagged with their source file."""
    chunks = retrieve(query)
    if not chunks:
        return "No matching documents found."
    return "\n\n".join(f'<document source="{c.source}">\n{c.text}\n</document>' for c in chunks)


# ---------- run_checklist ----------

@dataclass
class ChecklistStep:
    number: int
    text: str
    done: bool


def available_checklists(checklist_dir: Path = CHECKLIST_DIR) -> list[str]:
    return sorted(p.stem for p in checklist_dir.glob("*.md"))


def parse_checklist(path: Path) -> tuple[str, list[ChecklistStep]]:
    title, steps = path.stem, []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
        elif m := CHECKBOX.match(line):
            steps.append(ChecklistStep(number=len(steps) + 1, text=m.group(2).strip(), done=m.group(1).lower() == "x"))
    return title, steps


def run_checklist(checklist_name: str, checklist_dir: Path = CHECKLIST_DIR) -> str:
    """Walk a checklist and report progress: which steps are done, which are pending, what's next.

    Step status comes from the markdown checkboxes. In a real system each step would call
    an API (CI status, release tracker, pager) — that's the part we mock.
    """
    # Allow-list, not a path check: model output is untrusted input, so "../secrets" must never resolve
    known = available_checklists(checklist_dir)
    if checklist_name not in known:
        raise ValueError(f"Unknown checklist '{checklist_name}'. Available: {', '.join(known)}")
    path = checklist_dir / f"{checklist_name}.md"

    title, steps = parse_checklist(path)
    done = [s for s in steps if s.done]
    pending = [s for s in steps if not s.done]
    pct = round(100 * len(done) / len(steps)) if steps else 100

    lines = [f"{title} ({path.relative_to(config.DATA_DIR)}): {len(done)}/{len(steps)} steps done ({pct}%)", "", "DONE:"]
    lines += [f"  {s.number}. {s.text}" for s in done] or ["  (none)"]
    lines += ["", "PENDING:"]
    lines += [f"  {s.number}. {s.text}" for s in pending] or ["  (none)"]
    lines += ["", f"NEXT STEP: {pending[0].text}" if pending else "STATUS: complete — ready to proceed."]
    return "\n".join(lines)


# ---------- schemas Claude sees ----------

def tool_definitions() -> list[dict]:
    """The descriptions matter most: they are how Claude decides which tool fits a request."""
    return [
        {
            "name": "search_docs",
            "description": (
                "Search Orbit's release & operations knowledge base (runbooks, policies, on-call FAQ, "
                "checklists) and return the most relevant passages with their source file. Use this for "
                "any question about how something works, what a policy says, or what the steps of a "
                "procedure are."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "A focused search query."}},
                "required": ["query"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "name": "run_checklist",
            "description": (
                "Run a release checklist and report its live status: which steps are done, which are "
                "pending, and the next step. Use this when the user wants to check progress on, run, or "
                "walk through a checklist — not to explain what a checklist contains."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"checklist_name": {"type": "string", "enum": available_checklists()}},
                "required": ["checklist_name"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    ]


TOOL_FUNCTIONS = {"search_docs": search_docs, "run_checklist": run_checklist}


def execute_tool(name: str, tool_input: dict) -> tuple[str, bool]:
    """Run a tool by name. Returns (result_text, is_error) so failures go back to Claude, not crash the loop."""
    try:
        return TOOL_FUNCTIONS[name](**tool_input), False
    except Exception as e:  # noqa: BLE001 — any tool failure is reported to the model
        return f"Error: {e}", True
