"""Step 3 of RAG: augment the prompt with retrieved chunks and let Claude answer.

If no Anthropic credentials are configured, ask() runs in retrieval-only mode and
returns the chunks it *would* have sent, so the pipeline is testable for free.
"""

import os
from dataclasses import dataclass, field

import anthropic

from src import config
from src.retriever import RetrievedChunk, retrieve

SYSTEM_PROMPT = """You are ReleaseWise, an assistant for Orbit's release and operations engineers.

Answer the user's question using ONLY the documents provided in <documents>.
- Cite the source file for every fact, like [runbooks/rollback-procedure.md].
- If the documents do not contain the answer, say "I couldn't find that in the knowledge base"
  and do not guess. Engineers act on your answers during incidents, so a wrong answer is worse
  than no answer.
- Be concise. Use numbered steps when describing a procedure."""


@dataclass
class Answer:
    text: str
    sources: list[str]
    chunks: list[RetrievedChunk] = field(repr=False)
    llm_used: bool = True


def has_credentials() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


def format_context(chunks: list[RetrievedChunk]) -> str:
    """Wrap each chunk in a tagged block so Claude can tell documents apart and cite them."""
    blocks = [f'<document source="{c.source}">\n{c.text}\n</document>' for c in chunks]
    return "<documents>\n" + "\n".join(blocks) + "\n</documents>"


def _unique_sources(chunks: list[RetrievedChunk]) -> list[str]:
    return list(dict.fromkeys(c.source for c in chunks))


def generate(question: str, chunks: list[RetrievedChunk], client: anthropic.Anthropic | None = None) -> str:
    client = client or anthropic.Anthropic()
    response = client.beta.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"{format_context(chunks)}\n\nQuestion: {question}"}],
        # If a safety classifier declines, the API retries on a fallback model in the same call
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        return "The model declined to answer this question."
    return "".join(block.text for block in response.content if block.type == "text").strip()


def ask(question: str, k: int = config.TOP_K) -> Answer:
    chunks = retrieve(question, k=k)
    sources = _unique_sources(chunks)

    if not has_credentials():
        preview = "\n\n".join(f"--- {c.source} (relevance {c.score}) ---\n{c.text}" for c in chunks)
        return Answer(
            text="[retrieval-only mode: set ANTHROPIC_API_KEY in .env to get a written answer]\n\n" + preview,
            sources=sources,
            chunks=chunks,
            llm_used=False,
        )

    return Answer(text=generate(question, chunks), sources=sources, chunks=chunks)
