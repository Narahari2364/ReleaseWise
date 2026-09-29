import pytest

from src.ingest import build_index, load_documents, split_documents
from src.retriever import retrieve


@pytest.fixture(scope="session", autouse=True)
def index():
    build_index()


def test_loads_all_docs_with_metadata():
    docs = load_documents()
    assert len(docs) >= 9
    assert all(d.metadata["source"].endswith(".md") for d in docs)
    assert {d.metadata["doc_type"] for d in docs} == {"runbooks", "checklists"}


def test_chunks_carry_their_document_title():
    chunks = split_documents(load_documents())
    assert all(c.page_content.startswith("[") for c in chunks)


@pytest.mark.parametrize(
    "question, expected_source",
    [
        ("How do I roll back a bad release?", "runbooks/rollback-procedure.md"),
        ("How long does the canary run and at what traffic percentage?", "runbooks/deployment-process.md"),
        ("Who gets paged if the primary on-call doesn't acknowledge?", "runbooks/oncall-faq.md"),
        ("How often do we post status updates during a Sev-1?", "runbooks/incident-response.md"),
        ("Can I rename a column in a migration?", "runbooks/database-migrations.md"),
    ],
)
def test_top_result_comes_from_the_right_document(question, expected_source):
    assert retrieve(question)[0].source == expected_source
