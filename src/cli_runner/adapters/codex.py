from __future__ import annotations

import os

from cli_runner.adapters.base import AgentAdapter, InvocationSpec
from cli_runner.utils import resolve_command

class CodexAdapter(AgentAdapter):
    @property
    def name(self) -> str:
        return "codex"

    def resolve_cmd(self) -> list[str] | None:
        raw_cmd = os.environ.get("CODEX_RUNNER_CMD", "codex exec").strip().split()
        resolved = resolve_command(raw_cmd)
        return resolved if resolved and resolved[0] else None

    def build_invocation(self, prompt: str, resolved_cmd: list[str]) -> InvocationSpec:
        return InvocationSpec(
            argv=[*resolved_cmd, prompt],
            env_overrides={}
        )

    def is_installed(self) -> bool:
        return self.resolve_cmd() is not None

    def install(self, dry_run: bool = False) -> bool:
        print("Would install codex using: npm install -g @openai/codex")
        return True
