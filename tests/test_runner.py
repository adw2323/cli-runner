from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

from cli_orchestrator_ui.runner import (
    _completion_check_passes,
    _extract_completion_check,
    _extract_run_status,
    _run_codex_once,
    CompletionCheck,
    CompletionTargets,
    run_task_loop,
)


def test_run_task_loop_done_status_single_run() -> None:
    with patch(
        "cli_orchestrator_ui.runner._run_codex_once",
        return_value=(0, "work complete\nRUN_STATUS:DONE\n"),
    ) as run_once_mock:
        result = run_task_loop("do work", codex_cmd="codex exec", max_loops=4, strict_completion=False)
    assert result.status == "done"
    assert result.loops == 1
    assert result.return_code == 0
    sent_prompt = run_once_mock.call_args.args[1]
    assert "RUN_STATUS:DONE" in sent_prompt


def test_run_task_loop_continue_then_done() -> None:
    with patch(
        "cli_orchestrator_ui.runner._run_codex_once",
        side_effect=[(0, "RUN_STATUS:CONTINUE\n"), (0, "RUN_STATUS:DONE\n")],
    ):
        result = run_task_loop("do work", codex_cmd="codex exec", max_loops=4, strict_completion=False)
    assert result.status == "done"
    assert result.loops == 2
    assert result.return_code == 0


def test_run_task_loop_rework_returns_nonzero() -> None:
    with patch("cli_orchestrator_ui.runner._run_codex_once", return_value=(0, "RUN_STATUS:REWORK\n")):
        result = run_task_loop("do work", codex_cmd="codex exec", max_loops=4, strict_completion=False)
    assert result.status == "rework"
    assert result.return_code == 2


def test_run_task_loop_hits_loop_limit() -> None:
    with patch("cli_orchestrator_ui.runner._run_codex_once", return_value=(0, "RUN_STATUS:CONTINUE\n")):
        result = run_task_loop("do work", codex_cmd="codex exec", max_loops=2, strict_completion=False)
    assert result.status == "continue"
    assert result.loops == 2
    assert result.return_code == 3


def test_run_task_loop_resolves_command_before_execution() -> None:
    with (
        patch("cli_orchestrator_ui.runner._resolve_command", return_value=["C:\\tools\\codex.cmd", "exec"]) as resolve_mock,
        patch("cli_orchestrator_ui.runner._run_codex_once", return_value=(0, "RUN_STATUS:DONE\n")) as run_once_mock,
    ):
        result = run_task_loop("do work", codex_cmd="codex exec", max_loops=2, strict_completion=False)
    assert result.status == "done"
    assert resolve_mock.call_count == 1
    assert run_once_mock.call_args.args[0][0] == "C:\\tools\\codex.cmd"


def test_extract_run_status_ignores_instruction_text_and_uses_last_status_line() -> None:
    output = (
        "user\n"
        "When you finish each run, include exactly one final line: "
        "RUN_STATUS:DONE or RUN_STATUS:CONTINUE or RUN_STATUS:REWORK.\n"
        "codex\n"
        "RUN_STATUS:CONTINUE\n"
    )
    assert _extract_run_status(output) == "continue"


def test_run_codex_once_uses_utf8_with_replacement() -> None:
    proc = MagicMock()
    proc.stdout = io.StringIO("RUN_STATUS:DONE\n")
    proc.wait.return_value = 0
    with patch("cli_orchestrator_ui.runner.subprocess.Popen", return_value=proc) as popen_mock:
        rc, output = _run_codex_once(["codex.cmd", "exec"], "task")
    assert rc == 0
    assert "RUN_STATUS:DONE" in output
    kwargs = popen_mock.call_args.kwargs
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["errors"] == "replace"


def test_run_task_loop_strict_completion_requires_second_done_pass() -> None:
    with patch(
        "cli_orchestrator_ui.runner._run_codex_once",
        side_effect=[
            (0, "RUN_STATUS:DONE\n"),
            (
                0,
                "ROADMAP_REVIEWED: n/a\nTODO_REVIEWED: n/a\nREMAINING_ITEMS: 0\nVALIDATION_RUN: yes\nRUN_STATUS:DONE\n",
            ),
        ],
    ) as run_once_mock:
        with patch("cli_orchestrator_ui.runner._discover_completion_targets", return_value=CompletionTargets([], [])):
            result = run_task_loop("finish project", codex_cmd="codex exec", max_loops=4, strict_completion=True)
    assert result.status == "done"
    assert result.loops == 2
    second_prompt = run_once_mock.call_args_list[1].args[1]
    assert "Completion gate:" in second_prompt


def test_run_task_loop_strict_completion_falls_back_to_continue_when_not_verified() -> None:
    with patch(
        "cli_orchestrator_ui.runner._run_codex_once",
        side_effect=[(0, "RUN_STATUS:DONE\n"), (0, "RUN_STATUS:DONE\n"), (0, "RUN_STATUS:CONTINUE\n")],
    ):
        with patch("cli_orchestrator_ui.runner._discover_completion_targets", return_value=CompletionTargets([], [])):
            result = run_task_loop("finish project", codex_cmd="codex exec", max_loops=3, strict_completion=True)
    assert result.status == "continue"
    assert result.loops == 3


def test_extract_completion_check_parses_fields() -> None:
    text = "ROADMAP_REVIEWED: yes\nTODO_REVIEWED: no\nREMAINING_ITEMS: 4\nVALIDATION_RUN: yes\n"
    check = _extract_completion_check(text)
    assert check.roadmap_reviewed == "yes"
    assert check.todo_reviewed == "no"
    assert check.remaining_items == 4
    assert check.validation_run == "yes"


def test_completion_check_requires_roadmap_and_todo_when_present() -> None:
    targets = CompletionTargets(roadmap_files=["docs/PROJECT.md"], todo_files=["docs/TODO.md"])
    check = CompletionCheck(roadmap_reviewed="yes", todo_reviewed="yes", remaining_items=0, validation_run="yes")
    assert _completion_check_passes(check, targets) is True
    missing_todo = CompletionCheck(roadmap_reviewed="yes", todo_reviewed="n/a", remaining_items=0, validation_run="yes")
    assert _completion_check_passes(missing_todo, targets) is False
