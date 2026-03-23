from __future__ import annotations

from cli_runner.adapters.base import AgentAdapter, InvocationSpec
from cli_runner.adapters.claude import ClaudeAdapter
from cli_runner.adapters.codex import CodexAdapter
from cli_runner.adapters.gemini import GeminiAdapter

REGISTRY: dict[str, type[AgentAdapter]] = {
    "codex": CodexAdapter,
    "gemini": GeminiAdapter,
    "claude": ClaudeAdapter,
}

def get_adapter(name: str) -> AgentAdapter:
    cls = REGISTRY.get(name.lower())
    if cls is None:
        raise ValueError(f"Unknown agent '{name}'. Choose: {', '.join(REGISTRY)}")
    return cls()

__all__ = ["AgentAdapter", "InvocationSpec", "get_adapter", "REGISTRY"]
