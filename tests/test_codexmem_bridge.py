from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from cli_runner.broker.codexmem import CodexMemBridge


class _Result:
    def __init__(self, returncode: int, stdout: str) -> None:
        self.returncode = returncode
        self.stdout = stdout


@pytest.mark.asyncio
async def test_load_recent_lines_filters_repo_and_formats(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "ok": True,
        "items": [
            {
                "ts": "2026-03-23T03:37:18.107523+00:00",
                "repoId": "other-repo",
                "cwd": "C:\\Users\\andrew.walsh\\other",
                "requestSummary": "skip me",
                "actionSummary": "other",
                "status": "completed",
            },
            {
                "ts": "2026-03-23T03:38:18.107523+00:00",
                "repoId": "cli-runner",
                "cwd": "C:\\Users\\andrew.walsh\\cli-runner",
                "requestSummary": "Fix Ctrl+C behavior",
                "actionSummary": "Added cleanup path",
                "status": "completed",
            },
        ],
    }

    def _run(*_args, **_kwargs):
        return _Result(0, json.dumps(payload))

    monkeypatch.setattr("cli_runner.broker.codexmem.subprocess.run", _run)
    bridge = CodexMemBridge(
        cwd=Path("C:\\Users\\andrew.walsh\\cli-runner"),
        repo_id="cli-runner",
    )
    lines = await bridge.load_recent_lines(limit=8, max_chars=120)
    assert len(lines) == 1
    assert "Fix Ctrl+C behavior" in lines[0]
    assert "[memory/system]" in lines[0]


@pytest.mark.asyncio
async def test_add_run_invokes_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = Mock(return_value=_Result(0, json.dumps({"ok": True})))
    monkeypatch.setattr("cli_runner.broker.codexmem.subprocess.run", spy)
    bridge = CodexMemBridge(
        cwd=Path("C:\\Users\\andrew.walsh\\cli-runner"),
        repo_id="cli-runner",
        branch="master",
    )
    await bridge.add_run(request="task text", summary="summary text", status="running")
    args = spy.call_args.args[0]
    assert "add-run" in args
    assert "--repo-id" in args
    assert "cli-runner" in args
    assert "--request" in args
    assert "--summary" in args


@pytest.mark.asyncio
async def test_load_recent_lines_returns_empty_when_disabled_or_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = CodexMemBridge(
        cwd=Path("C:\\Users\\andrew.walsh\\cli-runner"),
        repo_id="cli-runner",
    )
    monkeypatch.setattr(bridge, "_enabled", False)
    assert bridge.enabled is False
    assert await bridge.load_recent_lines(limit=10, max_chars=80) == []

    async def payload_not_ok(_args):
        return {"ok": False}

    monkeypatch.setattr(bridge, "_enabled", True)
    monkeypatch.setattr(bridge, "_run_cli_json", payload_not_ok)
    assert await bridge.load_recent_lines(limit=10, max_chars=80) == []

    async def payload_bad_items(_args):
        return {"ok": True, "items": "not-a-list"}

    monkeypatch.setattr(bridge, "_run_cli_json", payload_bad_items)
    assert await bridge.load_recent_lines(limit=10, max_chars=80) == []


def test_queue_add_run_no_event_loop_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = CodexMemBridge(
        cwd=Path("C:\\Users\\andrew.walsh\\cli-runner"),
        repo_id="cli-runner",
    )
    monkeypatch.setattr("cli_runner.broker.codexmem.asyncio.get_running_loop", Mock(side_effect=RuntimeError()))
    bridge.queue_add_run(request="x", summary="y", status="running")


def test_queue_add_run_disabled_noop() -> None:
    bridge = CodexMemBridge(
        cwd=Path("C:\\Users\\andrew.walsh\\cli-runner"),
        repo_id="cli-runner",
    )
    bridge._enabled = False
    bridge.queue_add_run(request="x", summary="y", status="running")


def test_queue_add_run_schedules_task(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = CodexMemBridge(
        cwd=Path("C:\\Users\\andrew.walsh\\cli-runner"),
        repo_id="cli-runner",
    )
    created = Mock()
    fake_loop = Mock(create_task=created)
    monkeypatch.setattr("cli_runner.broker.codexmem.asyncio.get_running_loop", Mock(return_value=fake_loop))
    bridge.queue_add_run(request="x", summary="y", status="running")
    assert created.call_count == 1
    created.call_args.args[0].close()


@pytest.mark.asyncio
async def test_add_run_disabled_does_not_invoke(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = CodexMemBridge(
        cwd=Path("C:\\Users\\andrew.walsh\\cli-runner"),
        repo_id="cli-runner",
    )
    monkeypatch.setattr(bridge, "_enabled", False)
    run_cli = Mock()
    monkeypatch.setattr(bridge, "_run_cli_json", run_cli)
    await bridge.add_run(request="task", summary="summary", status="running")
    run_cli.assert_not_called()


@pytest.mark.asyncio
async def test_run_cli_json_handles_error_and_invalid_output(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = CodexMemBridge(
        cwd=Path("C:\\Users\\andrew.walsh\\cli-runner"),
        repo_id="cli-runner",
    )

    def raise_run(*_args, **_kwargs):
        raise OSError("boom")

    monkeypatch.setattr("cli_runner.broker.codexmem.subprocess.run", raise_run)
    assert await bridge._run_cli_json(["journal-list"]) is None

    monkeypatch.setattr("cli_runner.broker.codexmem.subprocess.run", Mock(return_value=_Result(1, "{}")))
    assert await bridge._run_cli_json(["journal-list"]) is None

    monkeypatch.setattr("cli_runner.broker.codexmem.subprocess.run", Mock(return_value=_Result(0, "not-json")))
    assert await bridge._run_cli_json(["journal-list"]) is None


def test_matches_repo_and_format_helpers() -> None:
    bridge = CodexMemBridge(
        cwd=Path("C:\\Users\\andrew.walsh\\cli-runner"),
        repo_id="cli-runner",
    )
    assert bridge._matches_repo("not-a-dict") is False
    assert bridge._matches_repo({"repoId": "cli-runner"}) is True
    assert bridge._matches_repo({"cwd": "C:\\Users\\andrew.walsh\\cli-runner\\subdir"}) is True

    assert bridge._parse_time("") == "??:??:??"
    assert bridge._parse_time("not-a-time") == "??:??:??"
    assert bridge._parse_time("2026-03-23T03:37:18Z") != "??:??:??"

    line = bridge._format_journal_line({"requestSummary": "", "actionSummary": "", "status": ""}, max_chars=80)
    assert "codex-mem entry" in line

    truncated = bridge._format_journal_line(
        {"requestSummary": "x" * 60, "actionSummary": "y" * 60, "status": "running"},
        max_chars=40,
    )
    assert "..." in truncated
