from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from cli_runner.broker.engine import BrokerEngine
from cli_runner.broker.models import RunState, TaskMode


@pytest.fixture
def events():
    collected = []

    def sink(event):
        collected.append(event)

    return collected, sink


@pytest.fixture(autouse=True)
def disable_pty(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BROKER_PTY", "0")


class _DummyProcess:
    def __init__(self) -> None:
        self.returncode = None
        self.terminated = False
        self.stdin = None

    def terminate(self) -> None:
        self.terminated = True


class _DummyPty:
    def __init__(self) -> None:
        self._alive = True
        self.terminated = False

    def isalive(self) -> bool:
        return self._alive

    def terminate(self, force: bool = False) -> None:
        self.terminated = True
        self._alive = False


class _SpawnedProcess:
    def __init__(self, pid: int = 999) -> None:
        self.pid = pid
        self.returncode: int | None = 0
        self.stdin = None
        self.stdout = None
        self.stderr = None

    async def wait(self) -> int:
        return 0


class _WaitProcess:
    def __init__(self, return_code: int) -> None:
        self._return_code = return_code

    async def wait(self) -> int:
        return self._return_code


def test_auto_continue_defaults_to_on(events, monkeypatch: pytest.MonkeyPatch) -> None:
    _, sink = events
    monkeypatch.delenv("AUTO_CONTINUE", raising=False)
    broker = BrokerEngine(sink=sink)
    assert broker.auto_continue is True


@pytest.mark.asyncio
@patch("cli_runner.broker.engine.asyncio.create_subprocess_exec", new_callable=AsyncMock)
async def test_start_file_not_found(mock_exec, events) -> None:
    collected, sink = events
    mock_exec.side_effect = FileNotFoundError()
    broker = BrokerEngine(sink=sink)
    await broker.start("task", TaskMode.CODEX_ONLY)
    assert broker.status.state == RunState.FAILED
    assert "not found" in broker.status.summary.lower()
    assert any("not found" in evt.message.lower() for evt in collected)


@pytest.mark.asyncio
@patch("cli_runner.broker.engine.asyncio.create_subprocess_exec", new_callable=AsyncMock)
async def test_start_codex_binary_uses_stdin_session_command(mock_exec, events) -> None:
    _, sink = events
    mock_exec.return_value = _SpawnedProcess()
    broker = BrokerEngine(sink=sink, codex_cmd=["codex"])
    send_mock = AsyncMock()
    broker._send_stdin = send_mock
    await broker.start("ship it", TaskMode.CODEX_ONLY)
    args = mock_exec.await_args.args
    assert os.path.basename(args[0]).lower() in {"codex", "codex.cmd", "codex.exe"}
    assert "exec" not in args
    sent_payload = send_mock.await_args.args[0]
    assert "ship it" in sent_payload
    assert "consult other models" in sent_payload.lower()


@pytest.mark.asyncio
async def test_continue_without_active_process_emits_guard(events) -> None:
    collected, sink = events
    broker = BrokerEngine(sink=sink, codex_cmd=["codex"])
    await broker.continue_task()
    assert any("no active process to continue" in evt.message.lower() for evt in collected)


@pytest.mark.asyncio
async def test_continue_with_active_non_stdin_session_emits_guard(events) -> None:
    collected, sink = events
    broker = BrokerEngine(sink=sink)
    broker._uses_stdin_session = False
    broker._process = _DummyProcess()
    await broker.continue_task()
    assert any("not stdin-driven" in evt.message.lower() for evt in collected)


@pytest.mark.asyncio
async def test_auto_continue_schedules_resume(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink, codex_cmd=["codex"])
    broker.auto_continue = True
    broker._process = _DummyProcess()
    broker.max_auto_loops = 3
    broker.auto_continue_delay_s = 0.0
    resume_mock = AsyncMock()
    broker.continue_task = resume_mock
    broker._schedule_auto_continue("process_exit")
    assert broker._auto_continue_task is not None
    await asyncio.wait_for(broker._auto_continue_task, timeout=1.0)
    resume_mock.assert_awaited_once()


def test_auto_continue_skips_on_terminal_completion_signal(events) -> None:
    collected, sink = events
    broker = BrokerEngine(sink=sink, codex_cmd=["codex"])
    broker.auto_continue = True
    broker._process = _DummyProcess()
    broker._saw_terminal_completion_signal = True
    broker._schedule_auto_continue("process_exit")
    assert broker._auto_continue_task is None
    assert any("terminal completion signal" in evt.message.lower() for evt in collected)


def test_auto_continue_skips_for_non_codex_command(events) -> None:
    collected, sink = events
    broker = BrokerEngine(sink=sink, codex_cmd=["python", "agent.py"])
    broker.auto_continue = True
    broker._uses_stdin_session = False
    broker._schedule_auto_continue("process_exit")
    assert broker._auto_continue_task is None
    assert any("not codex" in evt.message.lower() for evt in collected)


def test_completion_gate_not_requested_for_pty_session(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink, codex_cmd=["codex"])
    broker._pty_process = _DummyPty()
    assert broker._can_request_completion_gate() is False


def test_auto_continue_skips_when_no_active_session(events) -> None:
    collected, sink = events
    broker = BrokerEngine(sink=sink, codex_cmd=["codex"])
    broker.auto_continue = True
    broker._schedule_auto_continue("process_exit")
    assert broker._auto_continue_task is None
    assert any("no active codex session" in evt.message.lower() for evt in collected)


def test_auto_continue_limit_sets_paused(events) -> None:
    collected, sink = events
    broker = BrokerEngine(sink=sink, codex_cmd=["codex"])
    broker.auto_continue = True
    broker.max_auto_loops = 1
    broker.status.loop_count = 1
    broker._schedule_auto_continue("process_exit")
    assert broker.status.state == RunState.PAUSED
    assert any("limit reached" in evt.message.lower() for evt in collected)


def test_auto_continue_skips_on_blocked_state(events) -> None:
    collected, sink = events
    broker = BrokerEngine(sink=sink, codex_cmd=["codex"])
    broker.auto_continue = True
    broker._process = _DummyProcess()
    broker.status.state = RunState.BLOCKED
    broker.status.summary = "Codex requires a terminal to continue."
    broker._schedule_auto_continue("process_exit")
    assert broker._auto_continue_task is None
    assert any("state is blocked" in evt.message.lower() for evt in collected)


@pytest.mark.asyncio
async def test_auto_continue_skips_on_soft_blocked_state(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink, codex_cmd=["codex"])
    broker.auto_continue = True
    broker._process = _DummyProcess()
    broker.auto_continue_delay_s = 0.0
    broker.continue_task = AsyncMock()  # type: ignore[method-assign]
    broker.status.state = RunState.BLOCKED
    broker.status.summary = "If you want, I can continue with phase 4."
    broker._schedule_auto_continue("process_exit")
    assert broker._auto_continue_task is not None
    await asyncio.wait_for(broker._auto_continue_task, timeout=1.0)
    broker.continue_task.assert_awaited_once()  # type: ignore[attr-defined]


def test_auto_continue_skips_on_stopped_state(events) -> None:
    collected, sink = events
    broker = BrokerEngine(sink=sink, codex_cmd=["codex"])
    broker.auto_continue = True
    broker._process = _DummyProcess()
    broker.status.state = RunState.STOPPED
    broker._schedule_auto_continue("process_exit")
    assert broker._auto_continue_task is None
    assert any("state is stopped" in evt.message.lower() for evt in collected)


@pytest.mark.asyncio
@patch("cli_runner.broker.engine.asyncio.create_subprocess_exec", new_callable=AsyncMock)
async def test_start_os_error(mock_exec, events) -> None:
    collected, sink = events
    mock_exec.side_effect = OSError("boom")
    broker = BrokerEngine(sink=sink)
    await broker.start("task", TaskMode.CODEX_ONLY)
    assert broker.status.state == RunState.FAILED
    assert "failed to launch" in broker.status.summary.lower()
    assert any("failed to launch" in evt.message.lower() for evt in collected)


def test_build_codex_launch_command_non_codex_preserves_stdio_mode(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink, codex_cmd=["python", "agent.py"])
    cmd = broker._build_codex_launch_command("task")
    assert os.path.basename(cmd[0]).lower().startswith("python")
    assert cmd[1:] == ["agent.py"]
    assert broker._uses_stdin_session is True


def test_build_subprocess_env_does_not_force_venv(events, monkeypatch: pytest.MonkeyPatch) -> None:
    _, sink = events
    monkeypatch.setenv("PATH", "C:\\Windows\\System32")
    broker = BrokerEngine(sink=sink)
    env = broker._build_subprocess_env(Path.cwd())
    assert env["PATH"] == "C:\\Windows\\System32"
    assert "VIRTUAL_ENV" not in env


@pytest.mark.asyncio
async def test_start_empty_task(events) -> None:
    collected, sink = events
    broker = BrokerEngine(sink=sink)
    await broker.start("", TaskMode.CODEX_ONLY)
    assert any("task text is empty" in evt.message.lower() for evt in collected)


@pytest.mark.asyncio
async def test_start_while_running_guard(events) -> None:
    collected, sink = events
    broker = BrokerEngine(sink=sink)
    broker._process = _DummyProcess()
    await broker.start("task", TaskMode.CODEX_ONLY)
    assert any("already running" in evt.message.lower() for evt in collected)


@pytest.mark.asyncio
async def test_stop_active_process(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink)
    proc = _DummyProcess()
    broker._process = proc
    await broker.stop()
    assert proc.terminated is True
    assert broker.status.state == RunState.STOPPED


@pytest.mark.asyncio
async def test_retry_without_previous_task(events) -> None:
    collected, sink = events
    broker = BrokerEngine(sink=sink)
    await broker.retry()
    assert any("no previous task to retry" in evt.message.lower() for evt in collected)


@pytest.mark.asyncio
async def test_escalate_updates_summary(events) -> None:
    collected, sink = events
    broker = BrokerEngine(sink=sink)
    await broker.escalate()
    assert "escalate requested" in broker.status.summary.lower()
    assert any("surface intervention" in evt.message.lower() for evt in collected)


@pytest.mark.asyncio
@patch("cli_runner.broker.engine.asyncio.sleep", new_callable=AsyncMock)
async def test_retry_calls_start_again(_mock_sleep, events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink)
    broker._last_task_text = "hello"
    with patch.object(broker, "stop", new=AsyncMock()) as stop_mock:
        with patch.object(broker, "start", new=AsyncMock()) as start_mock:
            await broker.retry()
            stop_mock.assert_awaited_once()
            start_mock.assert_awaited_once_with("hello", broker.status.mode)


@pytest.mark.asyncio
async def test_shutdown_cancels_background_tasks(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink)

    async def _never() -> None:
        await asyncio.sleep(10)

    broker._stdout_task = asyncio.create_task(_never())
    broker._stderr_task = asyncio.create_task(_never())
    broker._wait_task = asyncio.create_task(_never())
    await broker.shutdown()
    assert broker._stdout_task.cancelled()
    assert broker._stderr_task.cancelled()
    assert broker._wait_task.cancelled()


@pytest.mark.asyncio
async def test_pump_stream_handles_none(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink)
    await broker._pump_stream(None, source=broker.status.active_agent, stream_name="stdout")


@pytest.mark.asyncio
async def test_wait_for_exit_preserves_hard_blocked_on_zero_return(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink)
    broker.status.state = RunState.BLOCKED
    broker.status.summary = "CLI requires a terminal (TTY)."
    await broker._wait_for_exit(_WaitProcess(0))
    assert broker.status.state == RunState.BLOCKED


@pytest.mark.asyncio
async def test_wait_for_exit_soft_blocked_zero_return_becomes_incomplete(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink)
    broker.status.state = RunState.BLOCKED
    broker.status.summary = "Need your input to proceed."
    await broker._wait_for_exit(_WaitProcess(0))
    assert broker.status.state == RunState.INCOMPLETE


@pytest.mark.asyncio
async def test_wait_for_exit_with_pending_completion_gate_pauses(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink)
    broker._completion_gate_pending = True
    await broker._wait_for_exit(_WaitProcess(0))
    assert broker.status.state == RunState.PAUSED
    assert "completion decision" in broker.status.summary.lower()


@pytest.mark.asyncio
async def test_wait_for_exit_preserves_incomplete_on_zero_return(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink)
    broker.status.state = RunState.INCOMPLETE
    await broker._wait_for_exit(_WaitProcess(0))
    assert broker.status.state == RunState.INCOMPLETE


@pytest.mark.asyncio
async def test_stop_active_pty_process(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink)
    pty = _DummyPty()
    broker._pty_process = pty
    await broker.stop()
    assert pty.terminated is True
    assert broker.status.state == RunState.STOPPED


@pytest.mark.asyncio
async def test_emergency_stop_terminates_active_process(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink)
    proc = _DummyProcess()
    broker._process = proc

    async def _never() -> None:
        await asyncio.sleep(10)

    broker._auto_continue_task = asyncio.create_task(_never())
    broker.emergency_stop()

    assert proc.terminated is True
    assert broker._auto_continue_task is None
    assert broker.status.state == RunState.STOPPED


def test_emergency_stop_terminates_active_pty(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink)
    pty = _DummyPty()
    broker._pty_process = pty
    broker.emergency_stop()
    assert pty.terminated is True
    assert broker.status.state == RunState.STOPPED


def test_emit_writes_log_file(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink)
    broker._emit(broker.status.active_agent, "hello-log")
    assert isinstance(broker._log_path, Path)
    assert broker._log_path.exists()
    assert "hello-log" in broker._log_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_start_records_memory_run(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink, codex_cmd=["codex"])
    broker._codex_mem.queue_add_run = Mock()  # type: ignore[method-assign]
    with patch("cli_runner.broker.engine.asyncio.create_subprocess_exec", new=AsyncMock(return_value=_SpawnedProcess())):
        broker._send_stdin = AsyncMock()  # type: ignore[method-assign]
        await broker.start("task", TaskMode.CODEX_ONLY)
    broker._codex_mem.queue_add_run.assert_called()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_preload_memory_journal_lines_delegates(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink)
    broker._codex_mem.load_recent_lines = AsyncMock(return_value=["one"])  # type: ignore[method-assign]
    lines = await broker.preload_memory_journal_lines(limit=8, max_chars=100)
    assert lines == ["one"]


@pytest.mark.asyncio
async def test_done_state_arms_completion_gate_and_requests_decision(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink, codex_cmd=["codex"])
    broker._process = _DummyProcess()
    broker.completion_gate_delay_s = 0.0
    broker._send_stdin = AsyncMock()  # type: ignore[method-assign]
    broker.status.state = RunState.DONE

    broker._handle_state_specific_actions("done")

    assert broker._completion_gate_pending is True
    assert broker._completion_gate_task is not None
    await asyncio.wait_for(broker._completion_gate_task, timeout=1.0)
    broker._send_stdin.assert_awaited_once()  # type: ignore[attr-defined]
    sent = broker._send_stdin.await_args.args[0]  # type: ignore[attr-defined]
    assert "DECISION:DONE" in sent
    assert broker.status.state == RunState.INCOMPLETE


@pytest.mark.asyncio
async def test_completion_gate_continue_decision_auto_resumes(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink, codex_cmd=["codex"])
    broker._process = _DummyProcess()
    broker.auto_continue = True
    broker.auto_continue_delay_s = 0.0
    broker.continue_task = AsyncMock()  # type: ignore[method-assign]
    broker._completion_gate_pending = True

    handled = broker._maybe_apply_completion_decision("DECISION:CONTINUE")

    assert handled is True
    assert broker.status.state == RunState.INCOMPLETE
    assert broker._auto_continue_task is not None
    await asyncio.wait_for(broker._auto_continue_task, timeout=1.0)
    broker.continue_task.assert_awaited_once()  # type: ignore[attr-defined]


def test_init_log_dir_honors_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    override = tmp_path / "broker-logs"
    monkeypatch.setenv("BROKER_LOG_DIR", str(override))
    created = BrokerEngine._init_log_dir()
    assert created == override
    assert created.exists()


def test_detect_git_branch_returns_unknown_on_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    result = Mock(returncode=1, stdout="")
    monkeypatch.setattr("cli_runner.broker.engine.subprocess.run", Mock(return_value=result))
    assert BrokerEngine._detect_git_branch(Path.cwd()) == "unknown"


def test_schedule_completion_gate_skips_when_pending(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink, codex_cmd=["codex"])
    broker._completion_gate_pending = True
    broker._schedule_completion_gate("done")
    assert broker._completion_gate_task is None


def test_schedule_completion_gate_skips_when_task_already_running(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink, codex_cmd=["codex"])
    broker._completion_gate_pending = False
    broker._completion_gate_task = Mock(done=Mock(return_value=False))
    with patch.object(broker, "_can_request_completion_gate", return_value=True):
        broker._schedule_completion_gate("done")
    assert broker._completion_gate_task is not None


def test_can_request_completion_gate_requires_stdin_and_codex(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink, codex_cmd=["codex"])
    broker._process = _DummyProcess()

    broker._uses_stdin_session = False
    assert broker._can_request_completion_gate() is False

    broker._uses_stdin_session = True
    broker.codex_cmd = ["python", "agent.py"]
    assert broker._can_request_completion_gate() is False


@pytest.mark.asyncio
async def test_request_completion_gate_returns_when_not_allowed(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink, codex_cmd=["codex"])
    broker.completion_gate_delay_s = 0.001
    broker._completion_gate_pending = True
    with patch.object(broker, "_can_request_completion_gate", return_value=False):
        await broker._request_completion_gate_after_delay()
    assert broker._completion_gate_pending is False


@pytest.mark.asyncio
async def test_request_completion_gate_cancelled_clears_pending(events, monkeypatch: pytest.MonkeyPatch) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink, codex_cmd=["codex"])
    broker.completion_gate_delay_s = 0.001
    broker._completion_gate_pending = True

    async def cancelled_sleep(_seconds: float) -> None:
        raise asyncio.CancelledError()

    monkeypatch.setattr("cli_runner.broker.engine.asyncio.sleep", cancelled_sleep)
    await broker._request_completion_gate_after_delay()
    assert broker._completion_gate_pending is False


@pytest.mark.asyncio
async def test_request_completion_gate_failure_sets_paused(events) -> None:
    collected, sink = events
    broker = BrokerEngine(sink=sink, codex_cmd=["codex"])
    broker._process = _DummyProcess()
    broker._completion_gate_pending = True
    broker.completion_gate_delay_s = 0.0
    broker._send_stdin = AsyncMock(side_effect=RuntimeError("send failed"))  # type: ignore[method-assign]
    await broker._request_completion_gate_after_delay()
    assert broker._completion_gate_pending is False
    assert broker.status.state == RunState.PAUSED
    assert "completion check failed" in broker.status.summary.lower()
    assert any("completion check failed" in evt.message.lower() for evt in collected)
