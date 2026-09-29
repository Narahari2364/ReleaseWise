"""Tests for the eval itself: a broken grader produces confident, wrong numbers."""

import pytest

from src import config
from src.evals import fact_present, grade_answer, load_cases, wilson_interval
from src.tools import TOOL_FUNCTIONS, run_checklist

CASES = load_cases()
BY_ID = {c["id"]: c for c in CASES}


def test_case_ids_unique_and_tools_valid():
    assert len(BY_ID) == len(CASES) >= 15
    assert all(c["expected_tool"] in TOOL_FUNCTIONS for c in CASES)


@pytest.mark.parametrize("case", [c for c in CASES if c["must_include"]], ids=lambda c: c["id"])
def test_gold_facts_exist_in_the_ground_truth(case):
    """Every expected fact must be findable in the docs (or the checklist tool output) — catches stale gold."""
    if case["expected_tool"] == "run_checklist":
        truth = run_checklist(case["expected_sources"][0].rsplit("/", 1)[-1].removesuffix(".md"))
    else:
        truth = "\n".join((config.DATA_DIR / s).read_text() for s in case["expected_sources"])
    for fact in case["must_include"]:
        assert fact_present(fact, truth), f"{case['id']}: '{fact}' not in {case['expected_sources']}"


def test_fact_alternatives_and_normalisation():
    assert fact_present("30 minutes|30 min", "hold for **30 min** then")
    assert fact_present("wednesday", "Released on WEDNESDAYS")
    assert not fact_present("30 minutes", "3 minutes")


# ---- oracle (should pass) and null (should fail) answers ----

def test_oracle_answer_passes_all_metrics():
    answer = "The canary gets 5% of traffic for 30 minutes [runbooks/deployment-process.md]."
    assert grade_answer(BY_ID["canary-traffic"], answer, ["search_docs"]) == {"correct": 1, "cited": 1, "tool_ok": 1}


@pytest.mark.parametrize("bad", ["", "I don't know.", "I couldn't find that in the knowledge base.",
                                 "The canary gets 10% of traffic for 1 hour [runbooks/deployment-process.md]."])
def test_null_and_wrong_answers_fail(bad):
    assert grade_answer(BY_ID["canary-traffic"], bad, ["search_docs"])["correct"] == 0


def test_answer_with_right_numbers_but_abstaining_fails():
    hedge = "I couldn't find that; maybe 5% for 30 minutes?"
    assert grade_answer(BY_ID["canary-traffic"], hedge, ["search_docs"])["correct"] == 0


def test_unanswerable_rewards_abstaining_and_punishes_invention():
    case = BY_ID["stipend-amount"]
    assert grade_answer(case, "The docs mention a stipend but don't specify the amount.", ["search_docs"])["correct"] == 1
    assert grade_answer(case, "I couldn't find that in the knowledge base.", ["search_docs"])["correct"] == 1
    assert grade_answer(case, "The weekly stipend is $500.", ["search_docs"])["correct"] == 0


def test_wrong_tool_is_recorded_separately_from_correctness():
    grade = grade_answer(BY_ID["hotfix-pending"], "Pending: regression test, back-ported fix.", ["search_docs"])
    assert grade["correct"] == 1 and grade["tool_ok"] == 0


def test_wilson_interval_is_sane():
    lo, hi = wilson_interval(18, 20)
    assert 0.6 < lo < 0.9 < hi <= 1.0


def test_citation_by_title_or_filename_counts():
    case = BY_ID["alert-silence"]
    assert grade_answer(case, "Up to 24 hours [runbooks/oncall-faq.md]", ["search_docs"])["cited"] == 1
    assert grade_answer(case, "Up to 24 hours, per the [On-Call FAQ].", ["search_docs"])["cited"] == 1
    assert grade_answer(case, "Up to 24 hours.", ["search_docs"])["cited"] == 0


def test_side_remark_does_not_fail_a_correct_answer_but_giving_up_does():
    case = BY_ID["postmortem-deadline"]
    ok = "Within 5 business days; the doc does not specify a different timeline for Sev-2."
    hedge = "Within 5 business days, but I couldn't find the exact Sev-2 rule."
    assert grade_answer(case, ok, ["search_docs"])["correct"] == 1
    assert grade_answer(case, hedge, ["search_docs"])["correct"] == 0
