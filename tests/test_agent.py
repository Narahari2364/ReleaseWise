"""Agent loop tests with a scripted fake Claude — no network, no API key, no cost."""

from types import SimpleNamespace

import pytest

from src.agent import MAX_STEPS, route_offline, run_agent


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
    result = run_agent("Where are we on the hotfix checklist?", client=client)

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
    run_agent("q", client=client)
    results = client.requests[1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["a", "b"]


def test_tool_errors_are_sent_back_to_the_model():
    client = ScriptedClient(
        reply("tool_use", tool_use("run_checklist", {"checklist_name": "missing"})),
        reply("end_turn", text("That checklist doesn't exist.")),
    )
    result = run_agent("q", client=client)
    assert result.tool_calls[0].is_error
    assert client.requests[1]["messages"][-1]["content"][0]["is_error"] is True


def test_loop_stops_at_max_steps():
    client = ScriptedClient(*[reply("tool_use", tool_use("search_docs", {"query": "x"})) for _ in range(MAX_STEPS)])
    result = run_agent("q", client=client)
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
