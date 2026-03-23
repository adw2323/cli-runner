from __future__ import annotations

import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from cli_runner.broker.engine import _resolve_command, derive_state_from_output
from cli_runner.broker.models import RunState


_RUN_STATUS_RE = re.compile(r"^\s*run_status\s*:\s*(done|continue|rework)\s*$", re.IGNORECASE | re.MULTILINE)
_RUN_STATUS_INSTRUCTION = (
    "When you finish each run, include exactly one final line: RUN_STATUS:DONE or RUN_STATUS:CONTINUE or RUN_STATUS:REWORK."
)
_DEFAULT_CONTINUE_PROMPT = (
    "Continue from where you left off. End with exactly one line: "
    "RUN_STATUS:DONE or RUN_STATUS:CONTINUE or RUN_STATUS:REWORK."
)
_STRICT_COMPLETION_PROMPT_TEMPLATE = (
    "Completion gate: before claiming DONE, verify whether the requested project work is truly complete.\n"
    "Do all of the following in this run:\n"
    "1) Check project planning/status docs when present (for example: README, PROJECT, TODO, ROADMAP, STATUS, execution board docs).\n"
    "2) Confirm no in-scope remaining work is listed.\n"
    "3) Run relevant validations/tests for changed code.\n"
    "4) Summarize why the project is complete or what remains.\n"
    "5) Include this completion checklist block exactly once (before final status line):\n"
    "ROADMAP_REVIEWED: yes|no|n/a\n"
    "TODO_REVIEWED: yes|no|n/a\n"
    "REMAINING_ITEMS: <integer>\n"
    "VALIDATION_RUN: yes|no|n/a\n"
    "If anything remains, output RUN_STATUS:CONTINUE.\n"
    "If blocked or fundamentally off-track, output RUN_STATUS:REWORK.\n"
    "Only output RUN_STATUS:DONE if completion is verified.\n\n"
    "Roadmap files detected:\n{roadmap_files}\n\n"
    "Todo files detected:\n{todo_files}\n\n"
    "Original task:\n{task_text}\n\n"
    "End with exactly one final line: RUN_STATUS:DONE or RUN_STATUS:CONTINUE or RUN_STATUS:REWORK."
)
_CHECK_ROADMAP_RE = re.compile(r"^\s*roadmap_reviewed\s*:\s*(yes|no|n/a)\s*$", re.IGNORECASE | re.MULTILINE)
_CHECK_TODO_RE = re.compile(r"^\s*todo_reviewed\s*:\s*(yes|no|n/a)\s*$", re.IGNORECASE | re.MULTILINE)
_CHECK_REMAINING_RE = re.compile(r"^\s*remaining_items\s*:\s*(\d+)\s*$", re.IGNORECASE | re.MULTILINE)
_CHECK_VALIDATION_RE = re.compile(r"^\s*validation_run\s*:\s*(yes|no|n/a)\s*$", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class RunnerResult:
    status: str
    loops: int
    return_code: int


@dataclass(frozen=True)
class CompletionTargets:
    roadmap_files: list[str]
    todo_files: list[str]


@dataclass(frozen=True)
class CompletionCheck:
    roadmap_reviewed: str | None
    todo_reviewed: str | None
    remaining_items: int | None
    validation_run: str | None


def _parse_cmd(raw: str) -> list[str]:
    return shlex.split(raw, posix=False)


def _ensure_run_status_instruction(task_text: str) -> str:
    trimmed = task_text.strip()
    if "run_status:" in trimmed.lower():
        return trimmed
    return f"{trimmed}\n\n{_RUN_STATUS_INSTRUCTION}"


def _extract_run_status(text: str) -> str | None:
    matches = list(_RUN_STATUS_RE.finditer(text))
    if not matches:
        return None
    return matches[-1].group(1).lower()


def _infer_status_from_output(text: str) -> str:
    state = RunState.RUNNING
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        state = derive_state_from_output(line, state)
    if state == RunState.DONE:
        return "done"
    if state in {RunState.INCOMPLETE, RunState.BLOCKED, RunState.PAUSED}:
        return "continue"
    return "rework"


def _run_codex_once(cmd: list[str], prompt: str) -> tuple[int, str]:
    proc = subprocess.Popen(
        [*cmd, prompt],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    if proc.stdout is None:
        raise RuntimeError("Failed to capture codex process output stream.")

    chunks: list[str] = []
    for line in proc.stdout:
        print(line, end="")
        chunks.append(line)
    proc.stdout.close()
    return_code = proc.wait()
    return return_code, "".join(chunks)


def _find_first_group(pattern: re.Pattern[str], text: str) -> str | None:
    matches = list(pattern.finditer(text))
    if not matches:
        return None
    return matches[-1].group(1).lower()


def _discover_completion_targets(root: Path) -> CompletionTargets:
    roadmap_candidates = [
        root / "ROADMAP.md",
        root / "PROJECT.md",
        root / "STATUS.md",
        root / "docs" / "ROADMAP.md",
        root / "docs" / "PROJECT.md",
        root / "docs" / "STATUS.md",
        root / "docs" / "EXECUTION_BOARD.md",
    ]
    todo_candidates = [
        root / "TODO.md",
        root / "docs" / "TODO.md",
    ]
    roadmap_files = [str(p.relative_to(root)) for p in roadmap_candidates if p.exists()]
    todo_files = [str(p.relative_to(root)) for p in todo_candidates if p.exists()]
    return CompletionTargets(roadmap_files=roadmap_files, todo_files=todo_files)


def _strict_completion_prompt(task_text: str, targets: CompletionTargets) -> str:
    roadmap_list = "\n".join(f"- {item}" for item in targets.roadmap_files) or "- (none detected)"
    todo_list = "\n".join(f"- {item}" for item in targets.todo_files) or "- (none detected)"
    return _STRICT_COMPLETION_PROMPT_TEMPLATE.format(
        task_text=task_text.strip(),
        roadmap_files=roadmap_list,
        todo_files=todo_list,
    )


def _extract_completion_check(text: str) -> CompletionCheck:
    remaining_raw = _find_first_group(_CHECK_REMAINING_RE, text)
    return CompletionCheck(
        roadmap_reviewed=_find_first_group(_CHECK_ROADMAP_RE, text),
        todo_reviewed=_find_first_group(_CHECK_TODO_RE, text),
        remaining_items=int(remaining_raw) if remaining_raw is not None else None,
        validation_run=_find_first_group(_CHECK_VALIDATION_RE, text),
    )


def _completion_check_passes(check: CompletionCheck, targets: CompletionTargets) -> bool:
    if check.remaining_items is None or check.remaining_items != 0:
        return False
    if check.validation_run not in {"yes", "n/a"}:
        return False
    if targets.roadmap_files and check.roadmap_reviewed != "yes":
        return False
    if targets.todo_files and check.todo_reviewed != "yes":
        return False
    return True


def run_task_loop(
    task_text: str,
    codex_cmd: str | None = None,
    max_loops: int = 8,
    strict_completion: bool = True,
) -> RunnerResult:
    raw_cmd = (codex_cmd or os.environ.get("CODEX_RUNNER_CMD") or "codex exec").strip()
    cmd = _resolve_command(_parse_cmd(raw_cmd))
    if not cmd:
        raise ValueError("CODEX_RUNNER_CMD resolved to an empty command.")

    prompt = _ensure_run_status_instruction(task_text)
    loops = 0
    completion_gate_pending = False
    completion_targets = _discover_completion_targets(Path.cwd())

    while True:
        loops += 1
        return_code, combined_output = _run_codex_once(cmd, prompt)
        status = _extract_run_status(combined_output) or _infer_status_from_output(combined_output)
        if status == "done":
            if strict_completion and not completion_gate_pending:
                if loops >= max_loops:
                    return RunnerResult(status="continue", loops=loops, return_code=3)
                completion_gate_pending = True
                prompt = _strict_completion_prompt(task_text, completion_targets)
                continue
            if strict_completion and completion_gate_pending:
                check = _extract_completion_check(combined_output)
                if not _completion_check_passes(check, completion_targets):
                    completion_gate_pending = False
                    if loops >= max_loops:
                        return RunnerResult(status="continue", loops=loops, return_code=3)
                    prompt = _DEFAULT_CONTINUE_PROMPT
                    continue
            return RunnerResult(status="done", loops=loops, return_code=0)
        if status == "rework":
            rc = return_code if return_code != 0 else 2
            return RunnerResult(status="rework", loops=loops, return_code=rc)
        if completion_gate_pending:
            completion_gate_pending = False
        if loops >= max_loops:
            return RunnerResult(status="continue", loops=loops, return_code=3)
        prompt = _DEFAULT_CONTINUE_PROMPT
