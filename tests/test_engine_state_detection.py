from pathlib import Path

import pytest

from cli_ai_runner.utils import resolve_command as _resolve_command, derive_state_from_output, strip_ansi
from cli_ai_runner.models import RunState


@pytest.mark.parametrize(
    ("line", "start", "expected"),
    [
        ("Waiting for input from user.", RunState.RUNNING, RunState.INCOMPLETE),
        ("Awaiting approval before continuing.", RunState.RUNNING, RunState.BLOCKED),
        ("Produced a partial result; task incomplete.", RunState.RUNNING, RunState.INCOMPLETE),
        ("Task is not completed yet.", RunState.RUNNING, RunState.INCOMPLETE),
        ("PAUSED due to approval request.", RunState.RUNNING, RunState.PAUSED),
        ("Task finished successfully.", RunState.RUNNING, RunState.DONE),
        ("completed successfully", RunState.RUNNING, RunState.DONE),
        ("Done", RunState.RUNNING, RunState.DONE),
        ("Operation completed with warnings.", RunState.RUNNING, RunState.RUNNING),
        ("Issue is unblocked after approval.", RunState.RUNNING, RunState.RUNNING),
        ("Agent was unpaused automatically.", RunState.RUNNING, RunState.RUNNING),
        ("Streaming output line", RunState.RUNNING, RunState.RUNNING),
        ("", RunState.RUNNING, RunState.RUNNING),
    ],
)
def test_state_derivation(line: str, start: RunState, expected: RunState) -> None:
    assert derive_state_from_output(line, start) == expected


def test_resolve_command_empty_list_passthrough() -> None:
    assert _resolve_command([]) == []


def test_resolve_command_absolute_path_passthrough(tmp_path: Path) -> None:
    fake = tmp_path / "tool.cmd"
    fake.write_text("@echo off\n", encoding="utf-8")
    assert _resolve_command([str(fake), "--flag"])[0] == str(fake)


def test_strip_ansi_removes_control_sequences() -> None:
    raw = "\x1b[?1049h\x1b[32mREADY\x1b[0m\r\n\x1b]0;title\x07\x07"
    cleaned = strip_ansi(raw)
    assert cleaned == "READY\n"
