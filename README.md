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

### The agent

```
request ──► Claude reads the tool descriptions and picks one
              ├─ search_docs(query)          → hybrid retrieval over the knowledge base
              └─ run_checklist(name)         → done / pending / next step for a checklist
            our loop runs the tool, returns the result, Claude answers (max 6 steps)
```

The loop is hand-written in `src/agent.py` (~30 lines), so the whole think → act → observe
cycle is visible. Tool errors go back to Claude as `is_error` results instead of crashing,
and checklist names are checked against an allow-list, because model output is untrusted input.
Without an API key, a keyword router stands in for Claude so the tools still work.

## Run it

```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # add your ANTHROPIC_API_KEY (optional: works retrieval-only without it)
.venv/bin/python -m src.app ingest
.venv/bin/python -m src.app ask "How do I roll back payments-api?"
.venv/bin/python -m src.app agent "What's pending on the pre-release checklist?"
.venv/bin/python -m src.app chat
.venv/bin/python -m pytest -q
```

## Status

- [x] Milestone 1 — RAG core (ingest, hybrid retrieval, grounded answers with citations)
- [x] Milestone 2 — Agent with `search_docs` + `run_checklist` tools
- [ ] Milestone 3 — Evals, Docker, GitHub Actions CI
