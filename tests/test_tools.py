import pytest

from src.tools import available_checklists, execute_tool, run_checklist, search_docs, tool_definitions


def test_lists_checklists_from_data_folder():
    assert available_checklists() == ["hotfix-checklist", "post-deploy-verification", "pre-release-checklist"]


def test_run_checklist_reports_done_pending_and_next_step():
    report = run_checklist("pre-release-checklist")
    assert "4/10 steps done (40%)" in report
    assert "NEXT STEP: Database migrations (if any) approved by the Database team" in report


def test_unknown_checklist_is_returned_as_error_not_raised():
    output, is_error = execute_tool("run_checklist", {"checklist_name": "nope"})
    assert is_error and "Available:" in output


def test_run_checklist_rejects_path_traversal():
    with pytest.raises(ValueError):
        run_checklist("../runbooks/rollback-procedure")


def test_search_docs_returns_tagged_sources():
    assert '<document source="runbooks/rollback-procedure.md">' in search_docs("how do I roll back a release")


def test_checklist_enum_matches_files():
    run_schema = next(t for t in tool_definitions() if t["name"] == "run_checklist")
    assert run_schema["input_schema"]["properties"]["checklist_name"]["enum"] == available_checklists()
