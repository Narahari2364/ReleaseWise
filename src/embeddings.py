"""Local embedding model, wrapped in LangChain's Embeddings interface.

An embedding turns text into a vector (a list of numbers, 384 of them for bge-small).
Texts with similar meaning end up as nearby vectors, so "how do I undo a deploy?"
lands close to the Rollback Procedure even though the words differ.
"""

from functools import lru_cache

from fastembed import TextEmbedding
from langchain_core.embeddings import Embeddings

from src import config


class LocalEmbeddings(Embeddings):
    """Any LangChain vector store accepts this, because it implements the two methods below."""

    def __init__(self, model_name: str = config.EMBEDDING_MODEL):
        self._model = TextEmbedding(model_name=model_name, cache_dir=str(config.EMBEDDING_CACHE_DIR))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [vec.tolist() for vec in self._model.passage_embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        # bge models embed questions slightly differently from passages for better matching
        return next(iter(self._model.query_embed(text))).tolist()


@lru_cache(maxsize=1)
def get_embeddings() -> LocalEmbeddings:
    """Load the model once per process; loading takes a second or two."""
    return LocalEmbeddings()
