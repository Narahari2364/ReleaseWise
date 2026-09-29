# ReleaseWise

![CI](../../actions/workflows/ci.yml/badge.svg)

An AI assistant for release & operations engineers. Ask *"How do I roll back payments-api?"*
and get an answer grounded in your runbooks with the source cited, or ask it to *"run the
pre-release checklist"* and it reports what's done, what's pending, and the next step.

Runs **entirely free and locally** on a laptop LLM (Ollama + Qwen 2.5 7B), or on the Claude API
by changing one setting.

**Stack:** Python · LangChain (text splitting, Chroma integration) · Chroma vector store ·
local embeddings (fastembed, bge-small) · BM25 · Ollama (Qwen 2.5 7B) / Claude API · tool calling ·
Streamlit · pytest · Docker · GitHub Actions

## Architecture

```
                    ┌──────────────────────── ingest ────────────────────────┐
  data/*.md  ──►  split into ~800-char chunks  ──►  embed locally  ──►  Chroma
                                                                          │
                    ┌──────────────────────── query ─────────────────────▼───┐
  question ──► LLM agent ── picks a tool from its description ──┐           │
                   ▲                                             ▼           │
                   │            search_docs(query)  ──►  hybrid retrieval:  │
                   │                                      vector search  ┐   │
                   │                                      BM25 keywords  ┴► RRF fusion → top 4 chunks
                   │            run_checklist(name) ──►  parse checklist → done / pending / next
                   │                                                │
                   └────────── tool result ◄────────────────────────┘
                   answer, citing [source-file.md]   (loop runs at most 6 tool steps)

  LLM = src/llm.py provider layer:  OllamaBackend (local, free)  |  AnthropicBackend (Claude API)
```

| File | Role |
|---|---|
| `src/ingest.py` | load markdown → chunk → embed → store in Chroma |
| `src/embeddings.py` | local embedding model behind LangChain's `Embeddings` interface |
| `src/retriever.py` | hybrid retrieval: vector + BM25, merged with Reciprocal Rank Fusion |
| `src/llm.py` | provider layer: one neutral interface, Ollama and Claude backends |
| `src/rag.py` | single-shot RAG: retrieved chunks + question → LLM → cited answer |
| `src/tools.py` | the agent's tools and the JSON schemas the model reads to choose between them |
| `src/agent.py` | the agent loop (think → call tool → observe → answer), hand-written |
| `src/evals.py` | retrieval eval (runs in CI) and end-to-end agent eval |
| `streamlit_app.py` | web UI over the same `run_agent()`, showing tool calls and sources |

## Run it

```bash
brew install ollama && brew services start ollama && ollama pull qwen2.5:7b   # free local LLM
python3.11 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
.venv/bin/python -m src.app ingest
.venv/bin/python -m src.app agent "What's pending on the pre-release checklist?"
.venv/bin/python -m src.app chat
.venv/bin/pytest -q
```

**Web UI:**

```bash
.venv/bin/streamlit run streamlit_app.py      # opens http://localhost:8501
```

A chat page where each answer shows which tool the agent called (click to see exactly what the
tool returned) and which documents it came from, plus a sidebar with live checklist progress,
model status and example questions.

To use Claude instead, set `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY` in `.env`.
If no LLM is reachable, everything still runs: `ask` shows the retrieved passages and the agent
falls back to a keyword router.

**Docker** (the embedding model and index are baked into the image; retrieval works with no network):

```bash
docker build -t releasewise .
docker run --rm -it -e OLLAMA_HOST=http://host.docker.internal:11434 releasewise chat
docker run --rm -p 8501:8501 -e OLLAMA_HOST=http://host.docker.internal:11434 \
  --entrypoint streamlit releasewise run streamlit_app.py --server.address 0.0.0.0   # web UI
```

## Evaluation

`evals/cases.json` holds 21 hand-written cases in five groups: single facts, procedures,
answers that need two documents, checklist runs, and **unanswerable** questions where the only
correct behaviour is to say "I couldn't find that". Grading is programmatic (each expected fact
is a short string with accepted variants, e.g. `30 minutes|30 min`), so it is free, deterministic
and explainable. The grader has its own tests: correct answers pass; empty answers, "I don't know",
wrong numbers and hedged answers fail; and every expected fact is checked to exist in the source
documents, so the answer key can't go stale.

**Retrieval eval** (15 answerable search cases, 95% Wilson CI):

| Retriever | Answer in top chunk | Answer in top 4 | Right source in top 4 |
|---|---|---|---|
| Vector only | 67% (42–85%) | 100% | 100% |
| BM25 keywords only | 73% (48–89%) | 93% | 93% |
| **Hybrid (vector + BM25, RRF)** | **87% (62–96%)** | **100%** | **100%** |

CI fails the build if "answer in top 4" drops below 90%.

**Agent eval** (all 21 cases through the real `run_agent()`, local Qwen 2.5 7B, $0):

| Variant | Correct | Cited source | Right tool | Avg latency |
|---|---|---|---|---|
| **Baseline prompt** | **20/21 (95%)** | **20/21 (95%)** | **21/21 (100%)** | ~10 s |
| v1: stricter citation + no-hedging prompt | 19/21 (90%) | 19/21 (90%) | 20/21 (95%) | ~10 s |

```bash
.venv/bin/python -m src.evals retrieval --mode vector      # reproduce a retrieval row
.venv/bin/python -m src.evals agent --variant baseline     # full agent run (free on Ollama)
.venv/bin/python -m src.evals rescore --variant baseline   # re-grade stored answers after a grader change
```

The runner records tokens, latency, the serving model and a full transcript per case, writes
each row as it finishes (so a crash resumes where it stopped), and logs API errors and timeouts
separately instead of scoring them as wrong answers.

**How the eval changed the project:**
1. The first agent run scored 67% on citations. Reading the failures showed the model *was*
   citing, by document title instead of file path, so the grader was fixed (titles count), not the model.
2. The remaining real failure was a right answer followed by "I couldn't find a specific duration".
   A v1 prompt targeted that, but it didn't fix it and made the 7B model pick the wrong tool on
   another question, so **v1 was rejected** and the baseline prompt kept.
3. Every grader change is re-applied to *all* stored runs (`rescore`), so variants are always
   compared under the same grader.

## Design decisions

- **Hybrid retrieval.** Pure vector search missed *"how often do we post status updates during a
  Sev-1?"*, because "Sev-1" appears in almost every document. BM25 matches exact terms like
  `Sev-1` or `payments-api`; vector search matches meaning ("undo a deploy" ≈ "rollback").
  Fusing both ranked the answer first more often than either alone.
- **Provider-agnostic LLM layer.** The agent loop speaks a neutral message format; each backend
  translates it (Ollama's OpenAI-style function calls vs Claude's `tool_use` blocks). Switching
  model is one setting, and the eval compares providers on identical cases.
- **Hand-written agent loop** instead of a framework agent: about 30 lines, and every step of
  the think → act → observe cycle is visible and unit-tested with scripted fake models.
- **Model output is untrusted input.** `run_checklist` only accepts names from an allow-list, so a
  model-supplied `../secrets` can't read arbitrary files. Tool errors go back to the model as
  `is_error` results rather than crashing the loop.
- **Local by default.** Local embeddings and a local LLM: $0 to run, and no data leaves the machine.

## What I learned

- Retrieval quality caps answer quality. An eval that only checked "is the answer in the top 4"
  scored 100% for every retriever and couldn't tell them apart; a stricter top-1 metric could.
- Read the failures before trusting the score. Two of three "failures" in the first agent run
  were the grader being too strict, not the model being wrong.
- A prompt change that looks obviously better can make a small model worse. Measure it.
- 21 cases give wide confidence intervals; one case is about 5 points. The eval catches regressions
  well but can't prove small improvements. More cases, not more decimal places.
- Running CI steps on a clean checkout caught two bugs that never showed up on my machine.

## Next steps

- Grow the eval set to 50+ cases with a held-out split, so prompt tuning can't overfit
- Compare Qwen 2.5 7B against Claude on the same eval (one flag: `--provider anthropic`)
- Re-ranking with a cross-encoder after hybrid retrieval
- Multi-turn memory in the chat UI (each question is answered independently today)
- Rebuild the agent loop as a LangGraph graph; expose tools over MCP
