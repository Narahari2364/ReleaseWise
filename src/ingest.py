"""Step 1 of RAG: load docs -> split into chunks -> embed -> store in Chroma.

Run with:  python -m src.app ingest
"""

import shutil
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src import config
from src.embeddings import get_embeddings
from src.retriever import get_keyword_index, get_vectorstore


def load_documents(data_dir: Path = config.DATA_DIR) -> list[Document]:
    """Read every .md file under data/ into a LangChain Document with source metadata."""
    docs = []
    for path in sorted(data_dir.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        title = next((line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("# ")), path.stem)
        docs.append(
            Document(
                page_content=text,
                metadata={
                    "source": str(path.relative_to(data_dir)),
                    "title": title,
                    "doc_type": path.parent.name,  # "runbooks" or "checklists"
                },
            )
        )
    return docs


def split_documents(docs: list[Document]) -> list[Document]:
    """Split on markdown section breaks first, then paragraphs, then sentences."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
        separators=["\n## ", "\n### ", "\n\n", "\n", ". ", " "],
    )
    chunks = splitter.split_documents(docs)
    for i, chunk in enumerate(chunks):
        chunk.metadata["chunk_id"] = i
        # Prefix the doc title so a chunk like "Steps (payments-api)" still knows it's about rollback
        chunk.page_content = f"[{chunk.metadata['title']}]\n{chunk.page_content}"
    return chunks


def build_index(data_dir: Path = config.DATA_DIR, persist_dir: Path = config.CHROMA_DIR) -> int:
    """Rebuild the vector store from scratch. Returns the number of chunks stored."""
    docs = load_documents(data_dir)
    if not docs:
        raise FileNotFoundError(f"No .md files found in {data_dir}")
    chunks = split_documents(docs)

    # Start clean so deleted/edited docs don't leave stale chunks behind
    shutil.rmtree(persist_dir, ignore_errors=True)
    Chroma.from_documents(
        documents=chunks,
        embedding=get_embeddings(),
        collection_name=config.COLLECTION_NAME,
        persist_directory=str(persist_dir),
        collection_metadata={"hnsw:space": "cosine"},
    )
    # Drop cached handles to the old index so the next retrieve() sees the new one
    get_vectorstore.cache_clear()
    get_keyword_index.cache_clear()
    return len(chunks)
