"""ReleaseWise web UI.

    streamlit run streamlit_app.py

A thin layer over the same run_agent() the CLI and the eval use. Nothing here changes
how answers are produced, it only shows the agent's work: which tool it picked, what the
tool returned, and which documents the answer came from.
"""

import re
import time

import streamlit as st

from src import config
from src.agent import run_agent
from src.ingest import build_index
from src.llm import get_backend
from src.tools import CHECKLIST_DIR, available_checklists, parse_checklist

EXAMPLES = [
    "How do I roll back payments-api if the release had a database migration?",
    "What's pending on the pre-release checklist?",
    "How much traffic does the canary get, and for how long?",
    "Who do I escalate to if the primary on-call doesn't respond?",
]

st.set_page_config(page_title="ReleaseWise", page_icon="🛠️", layout="wide")

if not config.CHROMA_DIR.exists():
    with st.spinner("Building the search index (first run only)..."):
        build_index()

backend = get_backend()
online = backend.available()


# ---------- sidebar: model status, live checklists, examples ----------

def sources_from(tool_outputs: list[str]) -> list[str]:
    found = []
    for out in tool_outputs:
        found += re.findall(r'source="([^"]+)"', out) + re.findall(r"\((checklists/[^)]+\.md)\)", out)
    return list(dict.fromkeys(found))


with st.sidebar:
    st.header("Model")
    if online:
        st.badge(f"{backend.name} · {backend.model}", icon=":material/check_circle:", color="green")
    else:
        st.badge("offline: keyword routing", icon=":material/warning:", color="orange")
        st.caption("No LLM reachable. Start Ollama (`brew services start ollama`) for real answers.")

    st.header("Checklists")
    for name in available_checklists():
        title, steps = parse_checklist(CHECKLIST_DIR / f"{name}.md")
        done = sum(s.done for s in steps)
        st.progress(done / len(steps), text=f"**{title}**: {done}/{len(steps)}")
        pending = [s for s in steps if not s.done]
        if pending:
            st.caption(f"Next: {pending[0].text}")

    st.header("Try asking")
    for q in EXAMPLES:
        if st.button(q, use_container_width=True):
            st.session_state.pending = q

    st.divider()
    if st.button("Rebuild search index", icon=":material/refresh:"):
        with st.spinner("Re-indexing data/..."):
            n = build_index()
        st.toast(f"Indexed {n} chunks")


# ---------- chat ----------

st.title("ReleaseWise")
st.caption("Ask about Orbit's runbooks, or ask it to run a release checklist. Answers cite their source documents.")

if "messages" not in st.session_state:
    st.session_state.messages = []


def unlink(markdown: str) -> str:
    """Models like to write [Guide](runbooks/x.md); those relative links are dead in a browser."""
    return re.sub(r"\[([^\]]+)\]\(([^)\s]+\.md)\)", r"\1 (`\2`)", markdown)


def render_assistant(msg: dict) -> None:
    for call in msg["tool_calls"]:
        args = ", ".join(f"{k}={v!r}" for k, v in call["input"].items())
        with st.expander(f":material/build: {call['name']}({args})"):
            st.text(call["output"])
    if msg["llm_used"]:
        st.markdown(unlink(msg["content"]))
    else:
        st.info("Offline mode: no LLM, so here is the raw tool output (expand above).", icon=":material/info:")
    meta = f"{msg['latency']:.1f}s"
    if msg["sources"]:
        meta = "Sources: " + ", ".join(f"`{s}`" for s in msg["sources"]) + f" · {meta}"
    st.caption(meta)


for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant":
            render_assistant(msg)
        else:
            st.markdown(msg["content"])

question = st.chat_input("e.g. How do I roll back a bad release?", height=68) or st.session_state.pop("pending", None)
if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Thinking — picking a tool, reading the docs..."):
            start = time.perf_counter()
            result = run_agent(question, backend=backend)
            latency = time.perf_counter() - start
        outputs = [t["content"] for t in result.transcript if t["role"] == "tool_result"]
        if not result.llm_used:  # offline router doesn't record a transcript
            outputs = [result.text.split("\n\n", 1)[-1]]
        msg = {
            "role": "assistant",
            "content": result.text,
            "tool_calls": [{"name": c.name, "input": c.input, "output": out}
                           for c, out in zip(result.tool_calls, outputs)],
            "sources": sources_from(outputs),
            "llm_used": result.llm_used,
            "latency": latency,
        }
        render_assistant(msg)
    st.session_state.messages.append(msg)
