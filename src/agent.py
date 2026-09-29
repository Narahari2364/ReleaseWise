"""The agent: the LLM decides which tool to call, we run it, repeat until it has an answer.

    user question
        │
        ▼
    LLM (sees tool descriptions) ──► tool call: run_checklist("hotfix-checklist")
        ▲                                    │
        │                                    ▼
        └────────── tool result ◄──── our Python runs the function

The loop ends when the model replies without asking for a tool. The loop is provider-agnostic:
the same code drives a local Ollama model or Claude (see src/llm.py).
"""

import json
import re
from dataclasses import dataclass, field

from src.llm import LLMTurn, ToolResult, get_backend
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
    # Observability — what the eval runner records per case
    stop_reason: str | None = None  # of the final model call
    model: str | None = None  # as reported by the provider's response, not our config
    usage: dict = field(default_factory=dict)  # summed over every model call in the loop
    transcript: list[dict] = field(default_factory=list)  # user / tool_call / tool_result / assistant turns


def _add_usage(total: dict, turn: LLMTurn) -> None:
    for key, value in turn.usage.items():
        total[key] = total.get(key, 0) + value


def run_agent(question: str, backend=None) -> AgentResult:
    backend = backend or get_backend()
    if not backend.available():
        return run_offline(question)

    history: list[dict] = [{"role": "user", "content": question}]
    result = AgentResult(text="", transcript=[{"role": "user", "content": question}])

    for _ in range(MAX_STEPS):
        turn = backend.chat(SYSTEM_PROMPT, history, tools=tool_definitions())
        _add_usage(result.usage, turn)
        result.model, result.stop_reason = turn.model, turn.stop_reason

        if turn.stop_reason == "refusal":
            result.text = "The model declined to answer this question."
            return result
        if turn.stop_reason != "tool_use":
            result.text = turn.text
            result.transcript.append({"role": "assistant", "content": turn.text})
            return result

        # The model asked for one or more tools: run them all, send every result back together
        history.append({"role": "assistant", "turn": turn})
        results = []
        for use in turn.tool_uses:
            output, is_error = execute_tool(use.name, use.input)
            result.tool_calls.append(ToolCall(use.name, use.input, is_error))
            result.transcript.append({"role": "tool_call", "name": use.name, "content": json.dumps(use.input, indent=2)})
            result.transcript.append({"role": "tool_result", "name": use.name, "content": output})
            results.append(ToolResult(use.id, use.name, output, is_error))
        history.append({"role": "tool", "results": results})

    result.text = f"Stopped after {MAX_STEPS} tool steps without a final answer."
    return result


# ---------- offline mode (no LLM available) ----------

def route_offline(question: str) -> ToolCall:
    """A crude keyword router standing in for the LLM's judgement, so the tools work without a model.

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
    note = "[offline mode: keyword routing, no LLM — start Ollama (`ollama serve`) or set LLM_PROVIDER/API key]"
    return AgentResult(f"{note}\n\n{output}", [call], llm_used=False)
