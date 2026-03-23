from __future__ import annotations

from cli_runner.adapters.base import AgentAdapter, InvocationSpec
from cli_runner.utils import resolve_command

class GeminiAdapter(AgentAdapter):
    @property
    def name(self) -> str:
        return "gemini"

    def resolve_cmd(self) -> list[str] | None:
        resolved = resolve_command(["gemini"])
        return resolved if resolved and resolved[0] else None

    def build_invocation(self, prompt: str, resolved_cmd: list[str]) -> InvocationSpec:
        return InvocationSpec(
            argv=[*resolved_cmd, prompt],
            env_overrides={}
        )

    def is_installed(self) -> bool:
        return self.resolve_cmd() is not None

    def install(self, dry_run: bool = False) -> bool:
        print("Would install gemini using: npm install -g @google/gemini-cli")
        return True
