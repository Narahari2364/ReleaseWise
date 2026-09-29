import pytest

from src import config
from src.ingest import build_index


@pytest.fixture(scope="session", autouse=True)
def index(tmp_path_factory):
    """Build a throwaway vector store for the test run.

    Tests must never rebuild the real .chroma/ index: a running app (CLI chat, Streamlit)
    holds a handle to it, and rebuilding it underneath that app breaks its searches.
    """
    real_dir = config.CHROMA_DIR
    config.CHROMA_DIR = tmp_path_factory.mktemp("chroma")
    build_index()
    yield
    config.CHROMA_DIR = real_dir
