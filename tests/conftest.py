import pytest

from src.ingest import build_index


@pytest.fixture(scope="session", autouse=True)
def index():
    """Build the vector store once per test run, so tests work on a fresh checkout (e.g. in CI)."""
    build_index()
