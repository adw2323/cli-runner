from __future__ import annotations

from io import StringIO
from unittest.mock import patch, MagicMock

from cli_runner.main import main
from cli_runner.runner import RunnerResult


def test_main_cli_calls_runner() -> None:
    # Test 'run' subcommand explicitly
    with patch("sys.argv", ["prog", "run", "ship", "it"]):
        with patch(
            "cli_runner.main.run_task_loop",
            return_value=RunnerResult(status="done", loops=1, return_code=0),
        ) as run_mock:
            assert main() == 0
    run_mock.assert_called_once()
    kwargs = run_mock.call_args.kwargs
    assert kwargs["strict_completion"] is True


def test_main_cli_requires_task() -> None:
    # 'run' without task text should fail
    with patch("sys.argv", ["prog", "run"]):
        with patch("sys.stdin", StringIO("")):
            assert main() == 1


def test_main_cli_no_strict_completion_flag() -> None:
    with patch("sys.argv", ["prog", "run", "--no-strict-completion", "ship", "it"]):
        with patch(
            "cli_runner.main.run_task_loop",
            return_value=RunnerResult(status="done", loops=1, return_code=0),
        ) as run_mock:
            assert main() == 0
    kwargs = run_mock.call_args.kwargs
    assert kwargs["strict_completion"] is False

def test_main_cli_status_subcommand() -> None:
    with patch("sys.argv", ["prog", "status"]):
        with patch("cli_runner.main.run_status", return_value=0) as status_mock:
            assert main() == 0
    status_mock.assert_called_once()
