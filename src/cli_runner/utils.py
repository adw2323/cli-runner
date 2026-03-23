from __future__ import annotations

import os
import re
import shlex
import shutil
from pathlib import Path

from cli_runner.broker.models import RunState

# ANSI and Control Character patterns
_ANSI_RE = re.compile(
    r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[\(\)].|[P^_][^\x1b]*\x1b\\|[#%&*+./].|[@-Z\\-_])"
)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0B-\x1F\x7F]")

# State detection patterns
_BLOCKED_PATTERNS = (
    "blocked",
    "need your input",
    "awaiting approval",
    "approval required",
    "press enter to continue",
    "hit enter to continue",
)
_INCOMPLETE_PATTERNS = (
    "incomplete",
    "waiting for input",
    "unable to complete",
    "could not finish",
    "partial result",
    "not completed",
    "failed to complete",
    "did not complete",
)
_PAUSED_PATTERNS = (
    "paused",
    "pause requested",
)
_DONE_PHRASE_PATTERNS = (
    "all done",
    "task finished",
    "finished successfully",
    "completed successfully",
    "successfully completed",
)


def strip_ansi(text: str) -> str:
    """Removes ANSI escape sequences and carriage returns."""
    if not isinstance(text, str):
        if isinstance(text, bytes):
            text = text.decode("utf-8", errors="replace")
        else:
            text = str(text)
    text = _ANSI_RE.sub("", text)
    text = text.replace("\r", "")
    text = _CONTROL_CHAR_RE.sub("", text)
    return text


def resolve_command(cmd: list[str]) -> list[str]:
    """Resolves command path, preferring .cmd/.bat on Windows."""
    if not cmd:
        return cmd
    program = cmd[0]
    if os.path.isabs(program) and os.path.exists(program):
        return cmd
    if os.name == "nt" and "." not in os.path.basename(program):
        for ext in (".cmd", ".bat", ".exe"):
            candidate = shutil.which(program + ext)
            if candidate:
                return [candidate, *cmd[1:]]
    resolved = shutil.which(program)
    if resolved:
        return [resolved, *cmd[1:]]
    return cmd


def _contains_phrase(text: str, phrase: str) -> bool:
    return re.search(rf"\b{re.escape(phrase)}\b", text) is not None


def derive_state_from_output(line: str, current: RunState) -> RunState:
    """Infers the next RunState based on a line of output."""
    lowered = line.lower()
    if any(_contains_phrase(lowered, token) for token in _BLOCKED_PATTERNS):
        return RunState.BLOCKED
    if any(_contains_phrase(lowered, token) for token in _INCOMPLETE_PATTERNS):
        return RunState.INCOMPLETE
    if any(_contains_phrase(lowered, token) for token in _PAUSED_PATTERNS):
        return RunState.PAUSED
    stripped = lowered.strip()
    if any(_contains_phrase(lowered, token) for token in _DONE_PHRASE_PATTERNS) or stripped in {"done", "done."}:
        return RunState.DONE
    return current
