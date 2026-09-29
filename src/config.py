"""Central settings. Everything tunable lives here so experiments are one-line changes."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# Knowledge base + vector store locations
DATA_DIR = Path(os.getenv("RELEASEWISE_DATA_DIR", ROOT / "data"))
CHROMA_DIR = Path(os.getenv("RELEASEWISE_CHROMA_DIR", ROOT / ".chroma"))
COLLECTION_NAME = "releasewise"

# Chunking: ~800 characters is roughly one section of a runbook.
# Overlap keeps a sentence that straddles a boundary from being lost.
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100

# Embeddings run locally (free, no API key). bge-small is a small, strong English model.
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
EMBEDDING_CACHE_DIR = Path(os.getenv("RELEASEWISE_MODEL_CACHE", ROOT / ".cache" / "fastembed"))

# How many chunks to hand the LLM per question
TOP_K = 4

# LLM used to write the final answer
CLAUDE_MODEL = os.getenv("RELEASEWISE_MODEL", "claude-opus-5")
