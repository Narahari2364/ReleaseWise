"""Headless UI test: runs streamlit_app.py without a browser (Streamlit's AppTest)."""

from streamlit.testing.v1 import AppTest

from src import config


def offline_app(monkeypatch) -> AppTest:
    # Point at a closed port so the test never depends on a local Ollama being up
    monkeypatch.setattr(config, "OLLAMA_HOST", "http://127.0.0.1:9")
    return AppTest.from_file(str(config.ROOT / "streamlit_app.py"), default_timeout=60).run()


def test_sidebar_shows_offline_status_and_checklist_progress(monkeypatch):
    at = offline_app(monkeypatch)
    assert not at.exception
    labels = [p.proto.text for p in at.sidebar.get("progress")]
    assert any("Pre-Release Checklist**: 4/10" in label for label in labels)
    assert any("orange-badge" in m.value and "offline" in m.value for m in at.sidebar.markdown)


def test_question_runs_the_agent_and_shows_the_tool_call(monkeypatch):
    at = offline_app(monkeypatch)
    at.chat_input[0].set_value("Run the pre-release checklist").run()
    assert not at.exception
    assert at.expander[0].label.endswith("run_checklist(checklist_name='pre-release-checklist')")
    assert "4/10 steps done" in at.expander[0].get("text")[0].value
    assert "checklists/pre-release-checklist.md" in at.main.caption[-1].value


def test_example_button_asks_the_question(monkeypatch):
    at = offline_app(monkeypatch)
    at.sidebar.button[0].click().run()
    assert at.chat_message[0].markdown[0].value.startswith("How do I roll back payments-api")
