from __future__ import annotations

import os

from cli_ai_runner.adapters.base import AgentAdapter, InvocationSpec
from cli_ai_runner.utils import resolve_command

import shutil
import subprocess

class CodexAdapter(AgentAdapter):
    @property
    def name(self) -> str:
        return "codex"

    def resolve_cmd(self) -> list[str] | None:
        # Check environment override first
        env_cmd = os.environ.get("CODEX_RUNNER_CMD")
        if env_cmd:
            resolved = resolve_command(env_cmd.strip().split())
            return resolved if resolved and resolved[0] else None
        
        # Default to 'codex' and check path
        resolved = resolve_command(["codex"])
        if resolved and shutil.which(resolved[0]):
             # We assume 'exec' is the default subcommand for our runner
             return [resolved[0], "exec"]
        return None

    def build_invocation(self, prompt: str, resolved_cmd: list[str]) -> InvocationSpec:
        return InvocationSpec(
            argv=[*resolved_cmd, prompt],
            env_overrides={}
        )

    def is_installed(self) -> bool:
        cmd = resolve_command(["codex"])
        return bool(cmd and shutil.which(cmd[0]))

    def install(self, dry_run: bool = False) -> bool:
        cmd = ["npm", "install", "-g", "@openai/codex"]
        if dry_run:
            print(f"Would run: {' '.join(cmd)}")
            return True
        
        print(f"Running: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, check=True, shell=True)
            return True
        except subprocess.CalledProcessError:
            return False
