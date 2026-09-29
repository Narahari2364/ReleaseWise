# ReleaseWise

A RAG-powered release & operations assistant. Ask questions like *"How do I roll back
payments-api?"* and get answers grounded in runbooks, with the source document cited.

## How it works

```
data/*.md ──► chunk ──► embed (local bge-small) ──► Chroma vector store
                                                          │
question ──► hybrid retrieval (vector + BM25, fused with RRF) ──► top-4 chunks
                                                          │
                              Claude answers using only those chunks, citing sources
```

## Run it

```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # add your ANTHROPIC_API_KEY (optional: works retrieval-only without it)
.venv/bin/python -m src.app ingest
.venv/bin/python -m src.app ask "How do I roll back payments-api?"
.venv/bin/python -m src.app chat
.venv/bin/python -m pytest -q
```

## Status

- [x] Milestone 1 — RAG core (ingest, hybrid retrieval, grounded answers with citations)
- [ ] Milestone 2 — Agent with `search_docs` + `run_checklist` tools
- [ ] Milestone 3 — Evals, Docker, GitHub Actions CI
