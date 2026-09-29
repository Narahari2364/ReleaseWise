# ReleaseWise

![CI](../../actions/workflows/ci.yml/badge.svg)

An AI assistant for release & operations engineers. Ask *"How do I roll back payments-api?"*
and get an answer grounded in your runbooks with the source cited, or ask it to *"run the
pre-release checklist"* and it reports what's done, what's pending, and the next step.

**Stack:** Python · LangChain (text splitting, Chroma integration) · Chroma vector store ·
local embeddings (fastembed, bge-small) · BM25 · Claude API (tool use) · pytest · Docker · GitHub Actions

## Architecture

```
                    ┌──────────────────────── ingest ────────────────────────┐
  data/*.md  ──►  split into ~800-char chunks  ──►  embed locally  ──►  Chroma
                                                                          │
                    ┌──────────────────────── query ─────────────────────▼───┐
  question ──► Claude agent ── picks a tool from its description ──┐        │
                   ▲                                                ▼        │
                   │            search_docs(query)  ──►  hybrid retrieval:  │
                   │                                      vector search  ┐   │
                   │                                      BM25 keywords  ┴► RRF fusion → top 4 chunks
                   │            run_checklist(name) ──►  parse checklist → done / pending / next
                   │                                                │
                   └────────── tool result ◄────────────────────────┘
                   answer, citing [source-file.md]   (loop runs at most 6 tool steps)
```

| File | Role |
|---|---|
| `src/ingest.py` | load markdown → chunk → embed → store in Chroma |
| `src/embeddings.py` | local embedding model behind LangChain's `Embeddings` interface |
| `src/retriever.py` | hybrid retrieval: vector + BM25, merged with Reciprocal Rank Fusion |
| `src/rag.py` | single-shot RAG: retrieved chunks + question → Claude → cited answer |
| `src/tools.py` | the agent's tools and the JSON schemas Claude reads to choose between them |
| `src/agent.py` | the agent loop (think → call tool → observe → answer), hand-written |
| `src/evals.py` | retrieval eval (free, in CI) and end-to-end agent eval (uses the API) |

## Run it

```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env                 # add ANTHROPIC_API_KEY (optional — see below)
.venv/bin/python -m src.app ingest
.venv/bin/python -m src.app agent "What's pending on the pre-release checklist?"
.venv/bin/python -m src.app chat
.venv/bin/pytest -q
```

Without an API key everything still runs: `ask` shows the retrieved passages, and the agent
falls back to a keyword router instead of Claude.

**Docker** (the embedding model and index are baked into the image, so it runs with no network):

```bash
docker build -t releasewise .
docker run --rm -it --env-file .env releasewise chat
```

## Evaluation

`evals/cases.json` holds 21 hand-written cases in five groups: single facts, procedures,
answers that need two documents, checklist runs, and **unanswerable** questions where the only
correct behaviour is to say "I couldn't find that". Grading is programmatic (each expected fact
is a short string with accepted variants, e.g. `30 minutes|30 min`), so it is free, deterministic
and explainable. The grader has its own tests: correct answers pass; empty answers, "I don't know"
and wrong numbers fail; and every expected fact is checked to exist in the source documents, so the
answer key can't go stale.

**Retrieval eval** (15 answerable search cases, 95% Wilson CI):

| Retriever | Answer in top chunk | Answer in top 4 | Right source in top 4 |
|---|---|---|---|
| Vector only | 67% (42–85%) | 100% | 100% |
| BM25 keywords only | 73% (48–89%) | 93% | 93% |
| **Hybrid (vector + BM25, RRF)** | **87% (62–96%)** | **100%** | **100%** |

```bash
.venv/bin/python -m src.evals retrieval --mode vector     # reproduce any row
```

CI fails the build if "answer in top 4" drops below 90%.

**Agent eval** (all 21 cases, through the real `run_agent()`): scores *correct*, *cited source*
and *right tool* as separate metrics, records tokens/latency per case, saves full transcripts,
resumes after a crash, and keeps API errors and timeouts out of the score.

```bash
.venv/bin/python -m src.evals agent --limit 3    # pilot
.venv/bin/python -m src.evals agent --reps 2     # full run
```

## Design decisions

- **Hybrid retrieval.** Pure vector search missed *"how often do we post status updates during a
  Sev-1?"*, because "Sev-1" appears in almost every document. BM25 matches exact terms like
  `Sev-1` or `payments-api`; vector search matches meaning ("undo a deploy" ≈ "rollback").
  Fusing both ranked the answer first more often than either alone (table above).
- **Hand-written agent loop** instead of a framework agent: about 30 lines, and every step of
  the think → act → observe cycle is visible and unit-tested with a scripted fake model.
- **Model output is untrusted input.** `run_checklist` only accepts names from an allow-list, so a
  model-supplied `../secrets` can't read arbitrary files. Tool errors go back to the model as
  `is_error` results rather than crashing the loop.
- **Grounding over helpfulness.** The prompt tells the model a wrong answer is worse than no answer,
  and the eval checks that it abstains on unanswerable questions.
- **Local embeddings.** Free, private, and no second API key; the container works offline.

## What I learned

- Retrieval quality caps answer quality. An eval that only checked "is the answer somewhere in the
  top 4" scored 100% for every retriever, so it couldn't tell them apart; a stricter top-1 metric could.
- With 15 cases the confidence intervals are wide: hybrid's lead is consistent but not
  statistically significant. More cases, not more decimal places.
- Running CI steps on a clean checkout caught two bugs that never showed up on my machine.

## Next steps

- Re-ranking with a cross-encoder after hybrid retrieval
- Prompt caching for the system prompt + tool definitions to cut token cost
- Grow the eval set to 50+ cases and add an LLM-judge for answer completeness
- Streamlit UI; rebuild the agent loop as a LangGraph graph; expose tools over MCP
