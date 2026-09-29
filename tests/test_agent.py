"""Agent loop tests with a scripted fake Claude — no network, no API key, no cost."""

from types import SimpleNamespace

import pytest

from src.agent import MAX_STEPS, route_offline, run_agent
from src.llm import AnthropicBackend


def text(t):
    return SimpleNamespace(type="text", text=t)


def tool_use(name, tool_input, id="toolu_1"):
    return SimpleNamespace(type="tool_use", name=name, input=tool_input, id=id)


class ScriptedClient:
    """Returns pre-written responses in order and records every request the agent sends."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return self.responses.pop(0)


def reply(stop_reason, *content):
    return SimpleNamespace(stop_reason=stop_reason, content=list(content))


def test_agent_runs_requested_tool_and_feeds_result_back():
    client = ScriptedClient(
        reply("tool_use", tool_use("run_checklist", {"checklist_name": "hotfix-checklist"})),
        reply("end_turn", text("2 of 7 hotfix steps are done. [checklists/hotfix-checklist.md]")),
    )
    result = run_agent("Where are we on the hotfix checklist?", backend=AnthropicBackend(client=client))

    assert [c.name for c in result.tool_calls] == ["run_checklist"]
    assert result.text.startswith("2 of 7")
    # Second request must carry the tool result, linked to the tool_use id
    tool_result = client.requests[1]["messages"][-1]["content"][0]
    assert tool_result["tool_use_id"] == "toolu_1"
    assert "2/7 steps done" in tool_result["content"]


def test_parallel_tool_calls_return_in_one_message():
    client = ScriptedClient(
        reply(
            "tool_use",
            tool_use("search_docs", {"query": "canary"}, id="a"),
            tool_use("run_checklist", {"checklist_name": "pre-release-checklist"}, id="b"),
        ),
        reply("end_turn", text("done")),
    )
    run_agent("q", backend=AnthropicBackend(client=client))
    results = client.requests[1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["a", "b"]


def test_tool_errors_are_sent_back_to_the_model():
    client = ScriptedClient(
        reply("tool_use", tool_use("run_checklist", {"checklist_name": "missing"})),
        reply("end_turn", text("That checklist doesn't exist.")),
    )
    result = run_agent("q", backend=AnthropicBackend(client=client))
    assert result.tool_calls[0].is_error
    assert client.requests[1]["messages"][-1]["content"][0]["is_error"] is True


def test_loop_stops_at_max_steps():
    client = ScriptedClient(*[reply("tool_use", tool_use("search_docs", {"query": "x"})) for _ in range(MAX_STEPS)])
    result = run_agent("q", backend=AnthropicBackend(client=client))
    assert len(result.tool_calls) == MAX_STEPS and "Stopped" in result.text


@pytest.mark.parametrize(
    "question, expected_tool",
    [
        ("Run the pre-release checklist", "run_checklist"),
        ("What's pending on the hotfix checklist?", "run_checklist"),
        ("How do I roll back payments-api?", "search_docs"),
        ("What does the hotfix checklist say about canaries?", "search_docs"),
    ],
)
def test_offline_router(question, expected_tool):
    assert route_offline(question).name == expected_tool


# ---------- Ollama backend: same loop, different wire format ----------

class FakeOllama:
    """Mimics ollama.Client.chat: tool calls come back as message.tool_calls[].function."""

    def __init__(self, *messages):
        self.messages, self.requests = list(messages), []

    def chat(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(message=self.messages.pop(0), model="qwen2.5:7b", done_reason="stop",
                               prompt_eval_count=100, eval_count=20)

    def list(self):
        return SimpleNamespace(models=[SimpleNamespace(model="qwen2.5:7b")])


def ollama_msg(content="", calls=()):
    tool_calls = [SimpleNamespace(function=SimpleNamespace(name=n, arguments=a)) for n, a in calls]
    return SimpleNamespace(content=content, tool_calls=tool_calls or None)


def test_agent_loop_works_with_ollama_backend():
    from src.llm import OllamaBackend

    client = FakeOllama(
        ollama_msg(calls=[("run_checklist", {"checklist_name": "post-deploy-verification"})]),
        ollama_msg("3 of 7 steps done [checklists/post-deploy-verification.md]"),
    )
    result = run_agent("Where are we on post-deploy verification?", backend=OllamaBackend(client=client))

    assert [c.name for c in result.tool_calls] == ["run_checklist"]
    assert result.model == "qwen2.5:7b" and result.usage == {"input_tokens": 200, "output_tokens": 40}
    sent = client.requests[1]["messages"]
    assert sent[0]["role"] == "system"
    assert sent[-1] == {"role": "tool", "tool_name": "run_checklist", "content": sent[-1]["content"]}
    assert "3/7 steps done" in sent[-1]["content"]
    # Tools are translated into OpenAI-style function schemas
    assert client.requests[0]["tools"][0]["type"] == "function"


def test_unavailable_backend_falls_back_to_offline_router():
    class Down:
        def available(self):
            return False

    result = run_agent("Run the pre-release checklist", backend=Down())
    assert not result.llm_used and result.tool_calls[0].name == "run_checklist"
