from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from cli_runner.main import main
from cli_runner.runner import RunnerResult


def test_main_cli_calls_runner() -> None:
    with patch("sys.argv", ["prog", "ship", "it"]):
        with patch(
            "cli_runner.main.run_task_loop",
            return_value=RunnerResult(status="done", loops=1, return_code=0),
        ) as run_mock:
            assert main() == 0
    run_mock.assert_called_once()
    kwargs = run_mock.call_args.kwargs
    assert kwargs["strict_completion"] is True


def test_main_cli_requires_task() -> None:
    with patch("sys.argv", ["prog"]):
        with patch("sys.stdin", StringIO("")):
            assert main() == 1


def test_main_cli_no_strict_completion_flag() -> None:
    with patch("sys.argv", ["prog", "--no-strict-completion", "ship", "it"]):
        with patch(
            "cli_runner.main.run_task_loop",
            return_value=RunnerResult(status="done", loops=1, return_code=0),
        ) as run_mock:
            assert main() == 0
    kwargs = run_mock.call_args.kwargs
    assert kwargs["strict_completion"] is False
