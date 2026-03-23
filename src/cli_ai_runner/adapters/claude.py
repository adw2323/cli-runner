from __future__ import annotations

from cli_ai_runner.adapters.base import AgentAdapter, InvocationSpec
from cli_ai_runner.utils import resolve_command

import shutil
import subprocess

class ClaudeAdapter(AgentAdapter):
    @property
    def name(self) -> str:
        return "claude"

    def resolve_cmd(self) -> list[str] | None:
        resolved = resolve_command(["claude"])
        return resolved if resolved and resolved[0] else None

    def build_invocation(self, prompt: str, resolved_cmd: list[str]) -> InvocationSpec:
        return InvocationSpec(
            argv=[*resolved_cmd, prompt],
            env_overrides={}
        )

    def is_installed(self) -> bool:
        cmd = resolve_command(["claude"])
        return bool(cmd and shutil.which(cmd[0]))

    def install(self, dry_run: bool = False) -> bool:
        cmd = ["npm", "install", "-g", "@anthropic-ai/claude-code"]
        if dry_run:
            print(f"Would run: {' '.join(cmd)}")
            return True
        
        print(f"Running: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, check=True, shell=True)
            return True
        except subprocess.CalledProcessError:
            return False
