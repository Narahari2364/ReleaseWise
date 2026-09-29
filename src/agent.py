"""The agent: Claude decides which tool to call, we run it, repeat until Claude has an answer.

    user question
        │
        ▼
    Claude (sees tool descriptions) ──► tool_use: run_checklist("hotfix-checklist")
        ▲                                      │
        │                                      ▼
        └────────── tool_result ◄──── our Python runs the function

The loop ends when Claude replies without asking for a tool (stop_reason == "end_turn").
"""

import re
from dataclasses import dataclass, field

import anthropic

from src import config
from src.rag import has_credentials
from src.tools import available_checklists, execute_tool, tool_definitions

MAX_STEPS = 6  # safety cap so a confused model can't loop forever

SYSTEM_PROMPT = """You are ReleaseWise, an assistant for Orbit's release and operations engineers.

You have two tools:
- search_docs: look up runbooks, policies and procedures.
- run_checklist: check the live status of a release checklist.

Rules:
- Always use a tool before answering; never answer from memory about Orbit's processes.
- Cite the source file for every fact, like [runbooks/rollback-procedure.md].
- If the tools don't return the answer, say "I couldn't find that in the knowledge base".
  Engineers act on your answers during incidents, so a wrong answer is worse than none.
- Be concise. Use numbered steps for procedures."""


@dataclass
class ToolCall:
    name: str
    input: dict
    is_error: bool = False


@dataclass
class AgentResult:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    llm_used: bool = True


def run_agent(question: str, client: anthropic.Anthropic | None = None) -> AgentResult:
    if client is None and not has_credentials():
        return run_offline(question)

    client = client or anthropic.Anthropic()
    messages: list = [{"role": "user", "content": question}]
    calls: list[ToolCall] = []

    for _ in range(MAX_STEPS):
        response = client.beta.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=tool_definitions(),
            messages=messages,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )

        if response.stop_reason == "refusal":
            return AgentResult("The model declined to answer this question.", calls)
        if response.stop_reason != "tool_use":
            text = "".join(b.text for b in response.content if b.type == "text").strip()
            return AgentResult(text, calls)

        # Claude asked for one or more tools: run them all, send every result back in one message
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            output, is_error = execute_tool(block.name, block.input)
            calls.append(ToolCall(block.name, block.input, is_error))
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": output, "is_error": is_error})
        messages.append({"role": "user", "content": results})

    return AgentResult(f"Stopped after {MAX_STEPS} tool steps without a final answer.", calls)


# ---------- offline mode (no API key) ----------

def route_offline(question: str) -> ToolCall:
    """A crude keyword router standing in for Claude's judgement, so the tools are usable without a key.

    Comparing this to the real agent is a good interview point: rules like these break on
    phrasing they didn't anticipate, while the LLM routes from the tool *descriptions*.
    """
    q = question.lower()
    wants_status = re.search(r"\b(run|status|progress|pending|done|walk through|check|where are we)\b", q) is not None
    for name in available_checklists():
        keyword = name.removesuffix("-checklist").replace("-", " ")  # "pre release", "hotfix", ...
        if wants_status and (keyword in q or keyword.replace(" ", "-") in q):
            return ToolCall("run_checklist", {"checklist_name": name})
    return ToolCall("search_docs", {"query": question})


def run_offline(question: str) -> AgentResult:
    call = route_offline(question)
    output, call.is_error = execute_tool(call.name, call.input)
    note = "[offline mode: keyword routing, no LLM — set ANTHROPIC_API_KEY in .env for the real agent]"
    return AgentResult(f"{note}\n\n{output}", [call], llm_used=False)
