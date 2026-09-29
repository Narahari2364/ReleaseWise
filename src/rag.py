"""Step 3 of RAG: augment the prompt with retrieved chunks and let the LLM answer.

If no LLM is available (Ollama not running, no API key), ask() runs in retrieval-only mode
and returns the chunks it *would* have sent, so the pipeline still works.
"""

from dataclasses import dataclass, field

from src import config
from src.llm import get_backend
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


def format_context(chunks: list[RetrievedChunk]) -> str:
    """Wrap each chunk in a tagged block so the model can tell documents apart and cite them."""
    blocks = [f'<document source="{c.source}">\n{c.text}\n</document>' for c in chunks]
    return "<documents>\n" + "\n".join(blocks) + "\n</documents>"


def _unique_sources(chunks: list[RetrievedChunk]) -> list[str]:
    return list(dict.fromkeys(c.source for c in chunks))


def generate(question: str, chunks: list[RetrievedChunk], backend=None) -> str:
    backend = backend or get_backend()
    prompt = f"{format_context(chunks)}\n\nQuestion: {question}"
    turn = backend.chat(SYSTEM_PROMPT, [{"role": "user", "content": prompt}])
    if turn.stop_reason == "refusal":
        return "The model declined to answer this question."
    return turn.text


def ask(question: str, k: int = config.TOP_K, backend=None) -> Answer:
    chunks = retrieve(question, k=k)
    sources = _unique_sources(chunks)
    backend = backend or get_backend()

    if not backend.available():
        preview = "\n\n".join(f"--- {c.source} (relevance {c.score}) ---\n{c.text}" for c in chunks)
        return Answer(
            text="[retrieval-only mode: no LLM available — start Ollama or set LLM_PROVIDER]\n\n" + preview,
            sources=sources,
            chunks=chunks,
            llm_used=False,
        )

    return Answer(text=generate(question, chunks, backend), sources=sources, chunks=chunks)
