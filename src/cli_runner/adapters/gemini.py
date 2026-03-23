from __future__ import annotations

from cli_runner.adapters.base import AgentAdapter, InvocationSpec
from cli_runner.utils import resolve_command

import shutil
import subprocess

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
        cmd = resolve_command(["gemini"])
        return bool(cmd and shutil.which(cmd[0]))

    def install(self, dry_run: bool = False) -> bool:
        cmd = ["npm", "install", "-g", "@google/gemini-cli"]
        if dry_run:
            print(f"Would run: {' '.join(cmd)}")
            return True
        
        print(f"Running: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, check=True, shell=True)
            return True
        except subprocess.CalledProcessError:
            return False
