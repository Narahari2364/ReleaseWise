"""Step 2 of RAG: find the chunks most relevant to a question.

Hybrid retrieval = two searches, merged:
  * vector search  — matches by meaning ("undo a deploy" ~ "rollback")
  * BM25 keyword search — matches exact terms ("Sev-1", "payments-api", "status page")
Each search produces a ranking; Reciprocal Rank Fusion (RRF) combines them, so a chunk
that ranks well in either list rises to the top.
"""

import re
from dataclasses import dataclass
from functools import lru_cache

from langchain_chroma import Chroma
from rank_bm25 import BM25Okapi

from src import config
from src.embeddings import get_embeddings

RRF_K = 60  # standard RRF constant; dampens the gap between rank 1 and rank 2
CANDIDATES = 10  # how deep to look in each ranking before fusing


@dataclass
class RetrievedChunk:
    text: str
    source: str
    title: str
    score: float  # fused RRF score: higher = more relevant (only meaningful for ordering)


def tokenize(text: str) -> list[str]:
    # Keeps hyphenated terms like "sev-1" and "payments-api" as single tokens
    return re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", text.lower())


@lru_cache(maxsize=1)
def get_vectorstore() -> Chroma:
    persist_dir = config.CHROMA_DIR  # read at call time, so tests can point it at a temp dir
    if not persist_dir.exists():
        raise FileNotFoundError("Vector store not found. Run `python -m src.app ingest` first.")
    return Chroma(
        collection_name=config.COLLECTION_NAME,
        embedding_function=get_embeddings(),
        persist_directory=str(persist_dir),
    )


@lru_cache(maxsize=1)
def get_keyword_index() -> tuple[BM25Okapi, list[str], list[dict]]:
    """Build a BM25 index over the same chunks that are stored in Chroma."""
    stored = get_vectorstore().get(include=["documents", "metadatas"])
    texts, metas = stored["documents"], stored["metadatas"]
    return BM25Okapi([tokenize(t) for t in texts]), texts, metas


def _vector_ranking(question: str) -> list[tuple[str, dict]]:
    docs = get_vectorstore().similarity_search(question, k=CANDIDATES)
    return [(d.page_content, d.metadata) for d in docs]


def _keyword_ranking(question: str) -> list[tuple[str, dict]]:
    bm25, texts, metas = get_keyword_index()
    scores = bm25.get_scores(tokenize(question))
    top = sorted(range(len(texts)), key=lambda i: scores[i], reverse=True)[:CANDIDATES]
    return [(texts[i], metas[i]) for i in top if scores[i] > 0]


MODES = ("hybrid", "vector", "keyword")


def retrieve(question: str, k: int = config.TOP_K, mode: str = "hybrid") -> list[RetrievedChunk]:
    """mode="vector"/"keyword" exist for ablations: `python -m src.evals retrieval --mode vector`."""
    try:
        return _retrieve(question, k, mode)
    except FileNotFoundError:
        raise
    except Exception:  # noqa: BLE001
        # The index was rebuilt by another process (e.g. `ingest`) while we held a handle to
        # the old one ("Collection ... does not exist"). Reopen it and retry once.
        get_vectorstore.cache_clear()
        get_keyword_index.cache_clear()
        return _retrieve(question, k, mode)


def _retrieve(question: str, k: int, mode: str) -> list[RetrievedChunk]:
    rankings = []
    if mode in ("hybrid", "vector"):
        rankings.append(_vector_ranking(question))
    if mode in ("hybrid", "keyword"):
        rankings.append(_keyword_ranking(question))

    fused: dict[int, float] = {}
    by_id: dict[int, tuple[str, dict]] = {}
    for ranking in rankings:
        for rank, (text, meta) in enumerate(ranking):
            chunk_id = meta["chunk_id"]
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)
            by_id[chunk_id] = (text, meta)

    best = sorted(fused, key=fused.get, reverse=True)[:k]
    return [
        RetrievedChunk(
            text=by_id[i][0],
            source=by_id[i][1]["source"],
            title=by_id[i][1]["title"],
            score=round(fused[i], 4),
        )
        for i in best
    ]
