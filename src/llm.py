"""Provider layer: one interface, two backends (local Ollama, Claude API).

The agent loop speaks a neutral format and never touches a provider SDK directly:

    history entries:  {"role": "user", "content": str}
                      {"role": "assistant", "turn": LLMTurn}
                      {"role": "tool", "results": [ToolResult, ...]}

Each backend translates that history into its own wire format. Switching provider is one
setting (LLM_PROVIDER in .env), and the eval can compare models on identical cases.
"""

import json
import uuid
from dataclasses import dataclass, field

from src import config


@dataclass
class ToolUse:
    id: str
    name: str
    input: dict


@dataclass
class ToolResult:
    tool_use_id: str
    name: str
    content: str
    is_error: bool = False


@dataclass
class LLMTurn:
    text: str
    tool_uses: list[ToolUse]
    stop_reason: str  # "end_turn" | "tool_use" | "max_tokens" | "refusal"
    model: str | None
    usage: dict = field(default_factory=dict)  # input_tokens / output_tokens
    raw: object = None  # provider-native content, echoed back unchanged on the next call


class OllamaBackend:
    """Free local model. Ollama's tools use OpenAI-style {"type": "function", ...} schemas."""

    name = "ollama"

    def __init__(self, client=None, model: str = config.OLLAMA_MODEL):
        if client is None:
            import ollama

            client = ollama.Client(host=config.OLLAMA_HOST, timeout=120)
        self.client, self.model = client, model

    def available(self) -> bool:
        try:
            names = {m.model for m in self.client.list().models}
        except Exception:  # noqa: BLE001 — server not running
            return False
        return self.model in names or f"{self.model}:latest" in names

    @staticmethod
    def _tools(tools: list[dict]) -> list[dict]:
        return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                  "parameters": t["input_schema"]}} for t in tools]

    def _messages(self, system: str, history: list[dict]) -> list[dict]:
        out = [{"role": "system", "content": system}]
        for h in history:
            if h["role"] == "user":
                out.append({"role": "user", "content": h["content"]})
            elif h["role"] == "assistant":
                turn = h["turn"]
                out.append({"role": "assistant", "content": turn.text,
                            "tool_calls": [{"function": {"name": u.name, "arguments": u.input}} for u in turn.tool_uses]})
            else:
                out += [{"role": "tool", "tool_name": r.name, "content": r.content} for r in h["results"]]
        return out

    def chat(self, system: str, history: list[dict], tools: list[dict] | None = None) -> LLMTurn:
        response = self.client.chat(
            model=self.model,
            messages=self._messages(system, history),
            tools=self._tools(tools) if tools else None,
            options={"temperature": 0},  # deterministic-ish: same question, same answer
        )
        msg = response.message
        uses = [ToolUse(id=f"call_{uuid.uuid4().hex[:8]}", name=c.function.name,
                        input=c.function.arguments if isinstance(c.function.arguments, dict)
                        else json.loads(c.function.arguments or "{}"))
                for c in (msg.tool_calls or [])]
        stop = "tool_use" if uses else ("max_tokens" if response.done_reason == "length" else "end_turn")
        return LLMTurn(
            text=(msg.content or "").strip(),
            tool_uses=uses,
            stop_reason=stop,
            model=response.model,
            usage={"input_tokens": response.prompt_eval_count or 0, "output_tokens": response.eval_count or 0},
        )


class AnthropicBackend:
    """Claude API. Needs ANTHROPIC_API_KEY."""

    name = "anthropic"

    def __init__(self, client=None, model: str = config.CLAUDE_MODEL):
        self._client, self.model = client, model

    @property
    def client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    def available(self) -> bool:
        import os

        return self._client is not None or bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))

    @staticmethod
    def _messages(history: list[dict]) -> list[dict]:
        out = []
        for h in history:
            if h["role"] == "user":
                out.append({"role": "user", "content": h["content"]})
            elif h["role"] == "assistant":
                out.append({"role": "assistant", "content": h["turn"].raw})  # keeps thinking blocks intact
            else:
                out.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": r.tool_use_id, "content": r.content, "is_error": r.is_error}
                    for r in h["results"]]})
        return out

    def chat(self, system: str, history: list[dict], tools: list[dict] | None = None) -> LLMTurn:
        kwargs = {"tools": tools} if tools else {}
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=self._messages(history),
            # If a safety classifier declines, the API retries on a fallback model in the same call
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            **kwargs,
        )
        usage = getattr(response, "usage", None)
        return LLMTurn(
            text="".join(b.text for b in response.content if b.type == "text").strip(),
            tool_uses=[ToolUse(b.id, b.name, b.input) for b in response.content if b.type == "tool_use"],
            stop_reason=response.stop_reason,
            model=getattr(response, "model", None),
            usage={k: getattr(usage, k, 0) or 0 for k in ("input_tokens", "output_tokens")},
            raw=response.content,
        )


def get_backend(provider: str = config.LLM_PROVIDER):
    backends = {"ollama": OllamaBackend, "anthropic": AnthropicBackend}
    if provider not in backends:
        raise ValueError(f"LLM_PROVIDER must be one of {list(backends)}, got {provider!r}")
    return backends[provider]()
