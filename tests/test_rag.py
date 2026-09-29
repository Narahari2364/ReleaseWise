from types import SimpleNamespace

from src.rag import format_context, generate
from src.retriever import RetrievedChunk

CHUNKS = [RetrievedChunk(text="Canary is 5% for 30 minutes.", source="runbooks/deployment-process.md", title="Deployment", score=0.9)]


class FakeClient:
    """Stands in for anthropic.Anthropic so tests are free, fast and offline."""

    def __init__(self, stop_reason="end_turn"):
        self.calls = []
        response = SimpleNamespace(
            stop_reason=stop_reason,
            content=[SimpleNamespace(type="text", text="5% for 30 minutes [runbooks/deployment-process.md]")],
        )
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: self.calls.append(kw) or response))


def test_context_tags_each_chunk_with_its_source():
    assert '<document source="runbooks/deployment-process.md">' in format_context(CHUNKS)


def test_generate_sends_retrieved_context_and_returns_text():
    client = FakeClient()
    answer = generate("How long is the canary?", CHUNKS, client=client)
    assert "30 minutes" in answer
    prompt = client.calls[0]["messages"][0]["content"]
    assert "Canary is 5% for 30 minutes." in prompt and "How long is the canary?" in prompt


def test_generate_handles_refusal():
    assert "declined" in generate("q", CHUNKS, client=FakeClient(stop_reason="refusal"))
