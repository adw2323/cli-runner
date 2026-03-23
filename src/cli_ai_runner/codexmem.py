from __future__ import annotations

import asyncio
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def _coerce_enabled(value: str) -> bool:
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _parse_cli_cmd(raw: str) -> list[str]:
    return shlex.split(raw, posix=False)


class CodexMemBridge:
    """Best-effort CLI bridge for codex-mem journal reads/writes."""

    def __init__(self, cwd: Path, repo_id: str, branch: str = "unknown") -> None:
        self._cwd = cwd
        self._repo_id = repo_id
        self._branch = branch
        self._timeout_s = float(os.environ.get("CODEXMEM_TIMEOUT_S", "4.0"))
        enabled_raw = os.environ.get("CODEXMEM_ENABLED", "1")
        self._enabled = _coerce_enabled(enabled_raw)
        default_cli = f"{sys.executable} -m codexmem_azure_client.cli"
        self._cli_cmd = _parse_cli_cmd(os.environ.get("CODEXMEM_CLI_CMD", default_cli))

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def load_recent_lines(self, limit: int, max_chars: int) -> list[str]:
        if not self._enabled or limit < 1:
            return []
        payload = await self._run_cli_json(["journal-list", "--limit", str(max(20, limit * 4))])
        if not payload or not payload.get("ok"):
            return []
        items = payload.get("items")
        if not isinstance(items, list):
            return []
        filtered = [item for item in items if self._matches_repo(item)]
        # API is newest-first; reverse so panel shows oldest->newest.
        filtered = list(reversed(filtered[:limit]))
        lines: list[str] = []
        for item in filtered:
            line = self._format_journal_line(item, max_chars=max_chars)
            if line:
                lines.append(line)
        return lines

    def queue_add_run(self, request: str, summary: str, status: str) -> None:
        if not self._enabled:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.add_run(request=request, summary=summary, status=status))

    async def add_run(self, request: str, summary: str, status: str) -> None:
        if not self._enabled:
            return
        normalized_request = " ".join(request.split()).strip() or "operator_control"
        normalized_summary = " ".join(summary.split()).strip() or "run_update"
        args = [
            "add-run",
            "--cwd",
            str(self._cwd),
            "--repo-id",
            self._repo_id,
            "--branch",
            self._branch,
            "--request",
            normalized_request[:220],
            "--summary",
            normalized_summary[:320],
            "--status",
            status,
            "--store",
        ]
        await self._run_cli_json(args)

    async def _run_cli_json(self, args: list[str]) -> dict[str, Any] | None:
        command = [*self._cli_cmd, *args]

        def _invoke() -> dict[str, Any] | None:
            try:
                result = subprocess.run(
                    command,
                    cwd=str(self._cwd),
                    text=True,
                    capture_output=True,
                    timeout=self._timeout_s,
                    check=False,
                )
            except Exception:
                return None
            if result.returncode != 0:
                return None
            try:
                return json.loads(result.stdout)
            except Exception:
                return None

        return await asyncio.to_thread(_invoke)

    def _matches_repo(self, item: Any) -> bool:
        if not isinstance(item, dict):
            return False
        repo_id = str(item.get("repoId", "")).strip().lower()
        if repo_id and repo_id == self._repo_id.lower():
            return True
        item_cwd = str(item.get("cwd", "")).strip().lower()
        current_cwd = str(self._cwd).strip().lower()
        return bool(item_cwd and current_cwd and item_cwd.startswith(current_cwd))

    @staticmethod
    def _parse_time(raw: str) -> str:
        if not raw:
            return "??:??:??"
        normalized = raw.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return "??:??:??"
        return parsed.strftime("%H:%M:%S")

    def _format_journal_line(self, item: dict[str, Any], max_chars: int) -> str:
        timestamp = self._parse_time(str(item.get("ts", "")))
        request = str(item.get("requestSummary", "")).strip()
        action = str(item.get("actionSummary", "")).strip()
        status = str(item.get("status", "")).strip()
        if action and request:
            message = f"{request} -> {action}"
        else:
            message = action or request or "codex-mem entry"
        if status:
            message = f"{message} ({status})"
        if len(message) > max_chars:
            message = message[: max_chars - 3] + "..."
        return f"[{timestamp}] [memory/system] {message}"
