"""Evaluation harness: score ReleaseWise against evals/cases.json.

Two evals, because they answer different questions and cost different amounts:

  retrieval  (free, runs in CI)   Did search put the right document AND the answer text
                                  in front of the model? If not, no LLM can answer well.
  agent      (free via Ollama)    End to end through run_agent(): right answer, cited the
                                  source, used the expected tool, admitted "not found"
                                  on questions the docs can't answer.

Grading is programmatic (string checks on short facts like "30 minutes"), not an LLM judge:
deterministic, free, and every pass/fail is explainable.

    python -m src.evals retrieval --min-hit-rate 0.9
    python -m src.evals agent --limit 3            # pilot on 3 cases
    python -m src.evals agent --reps 2             # full run, 2 repetitions per case
Results land in evals/runs/<eval>/<variant>/ (results.jsonl, traces/, errors.jsonl).
"""

import argparse
import json
import math
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path

from src import config

CASES_PATH = config.ROOT / "evals" / "cases.json"
RUNS_DIR = config.ROOT / "evals" / "runs"
CASE_TIMEOUT_S = 180  # hard wall-clock ceiling per agent case
CONCURRENCY = 4

# Abstaining on an unanswerable question: any of these counts as "I don't know"
NOT_FOUND = re.compile(
    r"couldn't find|could not find|not in the knowledge base|no information|"
    r"(?:doesn't|does not|don't|do not) (?:specify|state|mention|include|contain|cover|say|list)|"
    r"not (?:specified|stated|mentioned|documented|listed|covered)"
)
# Hedging on an answerable question: only an explicit "couldn't find" fails a correct answer.
# (A side remark like "the doc doesn't specify a different timeline for Sev-2" is fine.)
GAVE_UP = re.compile(r"couldn't find|could not find|not in the knowledge base")


# ---------- grading (pure functions, unit-tested in tests/test_evals.py) ----------

def normalize(text: str) -> str:
    text = text.lower().replace("**", "").replace("`", "")
    text = text.replace("’", "'").replace("–", "-").replace("—", "-").replace(" ", " ")
    return re.sub(r"\s+", " ", text)


def fact_present(fact: str, text: str) -> bool:
    """A fact is 'a|b|c' — any one accepted phrasing counts."""
    norm = normalize(text)
    return any(normalize(alt) in norm for alt in fact.split("|"))


def has_all_facts(case: dict, text: str) -> bool:
    return all(fact_present(f, text) for f in case["must_include"])


def is_answerable(case: dict) -> bool:
    return bool(case["must_include"])


def doc_title(source: str) -> str:
    """The document's '# Heading', e.g. runbooks/oncall-faq.md -> 'On-Call FAQ'."""
    text = (config.DATA_DIR / source).read_text(encoding="utf-8")
    return next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), source)


def cites_source(case: dict, answer: str) -> bool:
    """Citing by file name OR by document title both let an engineer find the doc."""
    norm = normalize(answer)
    for source in case["expected_sources"]:
        if source.rsplit("/", 1)[-1] in answer or normalize(doc_title(source)) in norm:
            return True
    return False


def grade_answer(case: dict, answer: str, tools_used: list[str]) -> dict:
    """Three independent binary metrics, so a failure says *what* went wrong."""
    if is_answerable(case):
        correct = has_all_facts(case, answer) and not GAVE_UP.search(normalize(answer))
        cited = cites_source(case, answer)
    else:
        correct = bool(NOT_FOUND.search(normalize(answer)))
        cited = correct  # nothing to cite; abstaining is the right behaviour
    return {
        "correct": int(correct),
        "cited": int(cited),
        "tool_ok": int(case["expected_tool"] in tools_used),
    }


def grade_retrieval(case: dict, chunks) -> dict:
    sources = {c.source for c in chunks}
    return {
        # Strict: is the whole answer in the single best chunk? Discriminates between retrievers.
        "answer_at_1": int(bool(chunks) and has_all_facts(case, chunks[0].text)),
        # What the LLM actually sees: is the answer anywhere in the top-k? This is the CI gate.
        "answer_in_context": int(has_all_facts(case, "\n".join(c.text for c in chunks))),
        "source_hit": int(any(s in sources for s in case["expected_sources"])),
    }


def wilson_interval(passes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% CI for a pass rate — honest error bars for a small eval set."""
    if n == 0:
        return 0.0, 0.0
    p = passes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


# ---------- runners ----------

def load_cases() -> list[dict]:
    return json.loads(CASES_PATH.read_text())


def _write_state(flow_dir: Path, metrics: list[dict], perf_fields: list[dict]) -> None:
    flow_dir.mkdir(parents=True, exist_ok=True)
    (flow_dir / "_state.json").write_text(json.dumps({"metrics": metrics, "perf_fields": perf_fields}, indent=2))


def _summarize(rows: list[dict], metric_ids: list[str]) -> None:
    for metric in metric_ids:
        scored = [r["grade"][metric] for r in rows if r.get("status") == "ok"]
        passes, n = sum(scored), len(scored)
        lo, hi = wilson_interval(passes, n)
        print(f"  {metric:<18} {passes}/{n} = {passes / max(n, 1):.0%}   (95% CI {lo:.0%}-{hi:.0%})")


def run_retrieval_eval(variant: str, mode: str = "hybrid") -> float:
    from src.retriever import retrieve

    cases = [c for c in load_cases() if c["expected_tool"] == "search_docs" and is_answerable(c)]
    flow = RUNS_DIR / "retrieval"
    _write_state(
        flow,
        metrics=[
            {"id": "answer_at_1", "label": "answer @1", "kind": "binary"},
            {"id": "answer_in_context", "label": "answer in ctx", "kind": "binary"},
            {"id": "source_hit", "label": "source hit", "kind": "binary"},
        ],
        perf_fields=[{"id": "latency_s", "label": "latency", "unit": "s"}],
    )
    out = flow / variant
    (out / "traces").mkdir(parents=True, exist_ok=True)

    rows = []
    for case in cases:
        start = time.perf_counter()
        chunks = retrieve(case["question"], mode=mode)
        row = {
            "prompt_id": case["id"],
            "prompt": case["question"],
            "tags": case["tags"],
            "status": "ok",
            "grade": grade_retrieval(case, chunks),
            "latency_s": round(time.perf_counter() - start, 3),
            "meta": {"retrieved": [c.source for c in chunks], "mode": mode},
        }
        rows.append(row)
        trace = [
            {"role": "user", "content": case["question"]},
            {"role": "tool_call", "name": "retrieve", "content": json.dumps({"query": case["question"]})},
            {"role": "tool_result", "name": "retrieve",
             "content": "\n\n".join(f"[{c.source}  score={c.score}]\n{c.text}" for c in chunks)},
        ]
        (out / "traces" / f"{case['id']}_rep0.json").write_text(json.dumps(trace, indent=2))

    (out / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"Retrieval eval, {mode} search ({len(rows)} answerable search cases) -> {out.relative_to(config.ROOT)}")
    _summarize(rows, ["answer_at_1", "answer_in_context", "source_hit"])
    for r in rows:
        if not r["grade"]["answer_in_context"]:
            print(f"  MISS {r['prompt_id']}: retrieved {r['meta']['retrieved']}")
    return sum(r["grade"]["answer_in_context"] for r in rows) / len(rows)


def _run_agent_case(case: dict, backend) -> dict:
    from src.agent import run_agent

    start = time.perf_counter()
    result = run_agent(case["question"], backend=backend)
    latency = round(time.perf_counter() - start, 2)
    status = {"end_turn": "ok", "max_tokens": "truncated", "refusal": "refusal"}.get(result.stop_reason, "ok")
    return {
        "result": result,
        "row": {
            "prompt_id": case["id"],
            "prompt": case["question"],
            "tags": case["tags"],
            "status": status,
            "stop_reason": result.stop_reason,
            "grade": grade_answer(case, result.text, [c.name for c in result.tool_calls]) if status == "ok" else {},
            "model": result.model,
            "usage": result.usage,
            "latency_s": latency,
            "tool_calls": len(result.tool_calls),
            "meta": {"answer": result.text, "tools": [c.name for c in result.tool_calls]},
        },
    }


def run_agent_eval(variant: str, reps: int, limit: int | None, provider: str) -> None:
    from src.llm import get_backend

    backend = get_backend(provider)
    if not backend.available():
        hint = {"ollama": f"start Ollama and run `ollama pull {backend.model}`",
                "anthropic": "set ANTHROPIC_API_KEY in .env"}[provider]
        sys.exit(f"No {provider} model available: {hint}.")
    # A local model serves one request at a time; parallel calls would only queue and time out
    workers = 1 if provider == "ollama" else CONCURRENCY

    cases = load_cases()[:limit] if limit else load_cases()
    flow = RUNS_DIR / "agent"
    _write_state(
        flow,
        metrics=[
            {"id": "correct", "label": "correct", "kind": "binary"},
            {"id": "cited", "label": "cited source", "kind": "binary"},
            {"id": "tool_ok", "label": "right tool", "kind": "binary"},
        ],
        perf_fields=[
            {"id": "latency_s", "label": "latency", "unit": "s"},
            {"id": "tool_calls", "label": "tool calls"},
            {"id": "in_tokens", "label": "in tok"},
            {"id": "out_tokens", "label": "out tok"},
        ],
    )
    out = flow / variant
    (out / "traces").mkdir(parents=True, exist_ok=True)
    results_path, errors_path = out / "results.jsonl", out / "errors.jsonl"

    # Resume: skip (case, rep) pairs already scored, so a crash doesn't cost finished cases
    done = set()
    if results_path.exists():
        done = {(r["prompt_id"], r["rep"]) for r in map(json.loads, results_path.read_text().splitlines())}
    todo = [(c, rep) for rep in range(reps) for c in cases if (c["id"], rep) not in done]
    print(f"Agent eval: {len(todo)} runs ({len(cases)} cases x {reps} reps, {len(done)} already done) "
          f"on {provider}:{backend.model} -> {out.relative_to(config.ROOT)}")

    pool = ThreadPoolExecutor(max_workers=workers)
    futures = [(case, rep, pool.submit(_run_agent_case, case, backend)) for case, rep in todo]
    for case, rep, future in futures:
        try:
            outcome = future.result(timeout=CASE_TIMEOUT_S)
        except FutureTimeout:
            _append(errors_path, {"prompt_id": case["id"], "rep": rep, "failure_class": "timeout"})
            print(f"  TIMEOUT {case['id']}")
            continue
        except Exception as e:  # noqa: BLE001 — API/harness errors are not model failures
            _append(errors_path, {"prompt_id": case["id"], "rep": rep, "failure_class": "harness_error", "error": repr(e)})
            print(f"  ERROR {case['id']}: {e!r}")
            continue

        row, result = outcome["row"], outcome["result"]
        if row["model"] and not row["model"].startswith(backend.model):
            _append(errors_path, {"prompt_id": case["id"], "rep": rep, "failure_class": "served_model_mismatch",
                                  "model": row["model"], "usage": row["usage"]})
            print(f"  MODEL MISMATCH {case['id']}: served by {row['model']}")
            continue
        row["rep"] = rep
        row["in_tokens"] = row["usage"].get("input_tokens", 0)
        row["out_tokens"] = row["usage"].get("output_tokens", 0)
        _append(results_path, row)  # written as each case finishes
        (out / "traces" / f"{case['id']}_rep{rep}.json").write_text(json.dumps(result.transcript, indent=2))
        verdict = "PASS" if row["grade"].get("correct") else "FAIL"
        print(f"  {verdict} {case['id']} (rep {rep}, {row['latency_s']}s, tools={row['meta']['tools']})")
    pool.shutdown(wait=False, cancel_futures=True)

    rows = [json.loads(line) for line in results_path.read_text().splitlines()] if results_path.exists() else []
    print(f"\nSummary over {len(rows)} scored runs:")
    _summarize(rows, ["correct", "cited", "tool_ok"])
    not_ok = [r for r in rows if r["status"] != "ok"]
    if not_ok:
        print(f"  not scored: {len(not_ok)} ({', '.join(sorted({r['status'] for r in not_ok}))})")
    usage = {k: sum(r["usage"].get(k, 0) for r in rows) for k in ("input_tokens", "output_tokens")}
    print(f"  tokens used: {usage['input_tokens']:,} in / {usage['output_tokens']:,} out")


def rescore_agent_eval(variant: str) -> None:
    """Re-grade stored answers after a grader/case fix — no model calls, so it's instant and free."""
    path = RUNS_DIR / "agent" / variant / "results.jsonl"
    cases = {c["id"]: c for c in load_cases()}
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    for r in rows:
        if r["status"] == "ok":
            old, r["grade"] = r["grade"], grade_answer(cases[r["prompt_id"]], r["meta"]["answer"], r["meta"]["tools"])
            if old != r["grade"]:
                print(f"  {r['prompt_id']}: {old} -> {r['grade']}")
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"Re-scored {len(rows)} rows in {path.relative_to(config.ROOT)}:")
    _summarize(rows, ["correct", "cited", "tool_ok"])


def _append(path: Path, row: dict) -> None:
    with path.open("a") as f:
        f.write(json.dumps(row) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals")
    sub = parser.add_subparsers(dest="eval", required=True)
    r = sub.add_parser("retrieval", help="free retrieval-quality eval")
    r.add_argument("--variant", default="baseline")
    r.add_argument("--mode", choices=("hybrid", "vector", "keyword"), default="hybrid", help="retriever ablation")
    r.add_argument("--min-hit-rate", type=float, default=0.0, help="exit 1 if answer_in_context rate is below this")
    a = sub.add_parser("agent", help="end-to-end agent eval (free with Ollama, paid with Claude)")
    a.add_argument("--variant", default="baseline")
    a.add_argument("--provider", choices=("ollama", "anthropic"), default=config.LLM_PROVIDER)
    a.add_argument("--reps", type=int, default=1)
    a.add_argument("--limit", type=int, help="only the first N cases (for a pilot run)")
    s = sub.add_parser("rescore", help="re-grade a stored agent run after changing the grader")
    s.add_argument("--variant", default="baseline")
    args = parser.parse_args(argv)

    if args.eval == "retrieval":
        rate = run_retrieval_eval(args.variant, args.mode)
        if rate < args.min_hit_rate:
            print(f"FAILED: answer_in_context {rate:.0%} < required {args.min_hit_rate:.0%}")
            return 1
    elif args.eval == "rescore":
        rescore_agent_eval(args.variant)
    else:
        run_agent_eval(args.variant, args.reps, args.limit, args.provider)
    return 0


if __name__ == "__main__":
    sys.exit(main())
