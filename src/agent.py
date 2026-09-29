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

import json
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


USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


@dataclass
class AgentResult:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    llm_used: bool = True
    # Observability — what the eval runner records per case
    stop_reason: str | None = None  # of the final model call
    model: str | None = None  # as reported by the API response, not our config
    usage: dict = field(default_factory=dict)  # summed over every model call in the loop
    transcript: list[dict] = field(default_factory=list)  # user / tool_call / tool_result / assistant turns


def _add_usage(total: dict, response) -> None:
    usage = getattr(response, "usage", None)
    for key in USAGE_FIELDS:
        total[key] = total.get(key, 0) + (getattr(usage, key, 0) or 0)


def run_agent(question: str, client: anthropic.Anthropic | None = None) -> AgentResult:
    if client is None and not has_credentials():
        return run_offline(question)

    client = client or anthropic.Anthropic()
    messages: list = [{"role": "user", "content": question}]
    result = AgentResult(text="", transcript=[{"role": "user", "content": question}])

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
        _add_usage(result.usage, response)
        result.model = getattr(response, "model", None)
        result.stop_reason = response.stop_reason

        if response.stop_reason == "refusal":
            result.text = "The model declined to answer this question."
            return result
        if response.stop_reason != "tool_use":
            result.text = "".join(b.text for b in response.content if b.type == "text").strip()
            result.transcript.append({"role": "assistant", "content": result.text})
            return result

        # Claude asked for one or more tools: run them all, send every result back in one message
        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            output, is_error = execute_tool(block.name, block.input)
            result.tool_calls.append(ToolCall(block.name, block.input, is_error))
            result.transcript.append({"role": "tool_call", "name": block.name, "content": json.dumps(block.input, indent=2)})
            result.transcript.append({"role": "tool_result", "name": block.name, "content": output})
            tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": output, "is_error": is_error})
        messages.append({"role": "user", "content": tool_results})

    result.text = f"Stopped after {MAX_STEPS} tool steps without a final answer."
    return result


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
