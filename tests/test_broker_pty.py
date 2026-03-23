from __future__ import annotations

import asyncio
import types
from collections import deque
from unittest.mock import AsyncMock, patch

import pytest

from cli_orchestrator_ui.broker.engine import BrokerEngine
from cli_orchestrator_ui.broker.models import RunState, TaskMode


class _FakePty:
    def __init__(self, lines: list[str] | None = None, wait_code: int = 0) -> None:
        self.lines = deque(lines or [])
        self.wait_code = wait_code
        self.alive = True
        self.writes: list[str] = []
        self.pid = 4242
        self.terminated = False

    def isalive(self) -> bool:
        return self.alive

    def write(self, payload: str) -> None:
        self.writes.append(payload)

    def readline(self):
        if self.lines:
            line = self.lines.popleft()
            if not self.lines:
                self.alive = False
            return line
        self.alive = False
        return ""

    def wait(self) -> int:
        self.alive = False
        return self.wait_code

    def terminate(self, force: bool = False) -> None:
        self.terminated = True
        self.alive = False


class _FlakyWritePty(_FakePty):
    def __init__(self, lines: list[str] | None = None, wait_code: int = 0) -> None:
        super().__init__(lines=lines, wait_code=wait_code)
        self._write_attempts = 0

    def write(self, payload: str) -> None:
        self._write_attempts += 1
        if self._write_attempts == 1:
            raise RuntimeError("transient startup write failure")
        super().write(payload)


@pytest.fixture
def events():
    collected = []

    def sink(event):
        collected.append(event)

    return collected, sink


@pytest.fixture(autouse=True)
def zero_pty_send_delays(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BROKER_PTY_INITIAL_SEND_DELAY", "0")


@pytest.mark.asyncio
async def test_send_stdin_uses_pty_write(monkeypatch: pytest.MonkeyPatch, events) -> None:
    monkeypatch.setenv("BROKER_PTY", "1")
    _, sink = events
    broker = BrokerEngine(sink=sink)
    fake = _FakePty()
    broker._pty_process = fake
    await broker._send_stdin("continue\n")
    assert fake.writes
    assert "continue\r\n" in fake.writes[0]


@pytest.mark.asyncio
@patch("cli_orchestrator_ui.broker.engine.asyncio.create_subprocess_exec", new_callable=AsyncMock)
async def test_start_uses_pty_path_when_forced(mock_exec, monkeypatch: pytest.MonkeyPatch, events) -> None:
    monkeypatch.setenv("BROKER_PTY", "1")
    collected, sink = events
    fake = _FakePty(lines=["OpenAI Codex /model to change", "completed"])
    fake_mod = types.SimpleNamespace(PtyProcess=types.SimpleNamespace(spawn=lambda _cmd: fake))
    monkeypatch.setitem(__import__("sys").modules, "winpty", fake_mod)

    broker = BrokerEngine(sink=sink, codex_cmd=["codex"])
    await broker.start("do task", TaskMode.CODEX_ONLY)
    assert broker._wait_task is not None
    await asyncio.wait_for(broker._wait_task, timeout=2.0)
    assert any("do task" in write for write in fake.writes)
    assert mock_exec.await_count == 0
    assert any("pty" in evt.message.lower() for evt in collected)


@pytest.mark.asyncio
async def test_spawn_pty_missing_module_returns_false(monkeypatch: pytest.MonkeyPatch, events) -> None:
    monkeypatch.setenv("BROKER_PTY", "1")
    collected, sink = events
    broker = BrokerEngine(sink=sink, codex_cmd=["codex"])

    # Remove winpty module and make import fail by patching builtins.__import__ locally.
    import builtins
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "winpty":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    ok = await broker._spawn_codex_pty("task")
    assert ok is False
    assert any("falling back to pipes" in evt.message.lower() for evt in collected)


@pytest.mark.asyncio
async def test_wait_for_pty_exit_success(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink)
    broker._pty_process = _FakePty(wait_code=0)
    await broker._wait_for_pty_exit()
    assert broker.status.state == RunState.DONE


@pytest.mark.asyncio
async def test_wait_for_pty_exit_failure(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink)
    broker._pty_process = _FakePty(wait_code=2)
    await broker._wait_for_pty_exit()
    assert broker.status.state == RunState.FAILED


@pytest.mark.asyncio
async def test_wait_for_pty_exit_soft_blocked_zero_return_becomes_incomplete(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink)
    broker.status.state = RunState.BLOCKED
    broker.status.summary = "Need your input to proceed."
    broker._pty_process = _FakePty(wait_code=0)
    await broker._wait_for_pty_exit()
    assert broker.status.state == RunState.INCOMPLETE


@pytest.mark.asyncio
async def test_wait_for_pty_exit_with_pending_completion_gate_pauses(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink)
    broker._completion_gate_pending = True
    broker._pty_process = _FakePty(wait_code=0)
    await broker._wait_for_pty_exit()
    assert broker.status.state == RunState.PAUSED
    assert "completion decision" in broker.status.summary.lower()


@pytest.mark.asyncio
async def test_pump_pty_detects_tty_blocked(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink)
    broker._pty_process = _FakePty(lines=["stdin is not a terminal"])
    await broker._pump_pty_stream(source=broker.status.active_agent, stream_name="pty")
    assert broker.status.state == RunState.BLOCKED
    assert "tty" in broker.status.summary.lower()


@pytest.mark.asyncio
async def test_pump_pty_marks_prompt_ready(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink)
    broker._pty_process = _FakePty(lines=["OpenAI Codex /model to change"])
    await broker._pump_pty_stream(source=broker.status.active_agent, stream_name="pty")
    assert broker._pty_prompt_ready.is_set() is True


@pytest.mark.asyncio
async def test_send_initial_pty_task_waits_for_prompt_ready(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink)
    fake = _FakePty()
    broker._pty_process = fake

    await broker._send_initial_pty_task("do task")
    assert fake.writes == []
    broker._pty_prompt_ready.set()
    await broker._flush_initial_pty_task_if_ready()
    assert fake.writes == ["do task\r\n"]


@pytest.mark.asyncio
async def test_pump_pty_stream_flushes_queued_initial_task_on_ready_prompt(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink)
    fake = _FakePty(lines=["Use /skills to list available skills"])
    broker._pty_process = fake
    await broker._send_initial_pty_task("do task")
    await broker._pump_pty_stream(source=broker.status.active_agent, stream_name="pty")
    assert fake.writes == ["do task\r\n"]


@pytest.mark.asyncio
async def test_pump_pty_stream_multiple_ready_lines_submits_once(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink)
    fake = _FakePty(lines=["Use /skills to list available skills", "OpenAI Codex /model to change"])
    broker._pty_process = fake
    await broker._send_initial_pty_task("do task")
    await broker._pump_pty_stream(source=broker.status.active_agent, stream_name="pty")
    assert fake.writes == ["do task\r\n"]


@pytest.mark.asyncio
async def test_initial_pty_task_retries_when_first_write_fails(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink)
    flaky = _FlakyWritePty(lines=["Use /skills to list available skills", "OpenAI Codex /model to change"])
    broker._pty_process = flaky
    await broker._send_initial_pty_task("do task")
    await broker._pump_pty_stream(source=broker.status.active_agent, stream_name="pty")
    assert flaky.writes == ["do task\r\n"]


@pytest.mark.asyncio
async def test_initial_pty_task_watchdog_forces_injection_without_ready_signal(monkeypatch: pytest.MonkeyPatch, events) -> None:
    monkeypatch.setenv("BROKER_PTY_INITIAL_INJECT_MAX_WAIT", "0.01")
    _, sink = events
    broker = BrokerEngine(sink=sink)
    fake = _FakePty()
    broker._pty_process = fake
    await broker._send_initial_pty_task("do task")
    await asyncio.sleep(0.05)
    assert fake.writes == ["do task\r\n"]


@pytest.mark.asyncio
async def test_initial_pty_commit_nudge_sends_extra_submit(monkeypatch: pytest.MonkeyPatch, events) -> None:
    monkeypatch.setenv("BROKER_PTY_COMMIT_NUDGE_DELAY", "0.01")
    _, sink = events
    broker = BrokerEngine(sink=sink)
    fake = _FakePty(lines=["Use /skills to list available skills"])
    broker._pty_process = fake
    await broker._send_initial_pty_task("do task")
    await broker._pump_pty_stream(source=broker.status.active_agent, stream_name="pty")
    await asyncio.sleep(0.05)
    assert fake.writes == ["do task\r\n", "\r\n"]


@pytest.mark.asyncio
async def test_pump_pty_commits_queued_prompt_once(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink)
    fake = _FakePty(lines=["Use /skills to list available skills", "tab to queue message"])
    broker._pty_process = fake
    await broker._send_initial_pty_task("do task")
    await broker._pump_pty_stream(source=broker.status.active_agent, stream_name="pty")
    assert fake.writes == ["do task\r\n", "\r\n"]


@pytest.mark.asyncio
async def test_stop_pty_path(events) -> None:
    _, sink = events
    broker = BrokerEngine(sink=sink)
    fake = _FakePty(lines=[])
    broker._pty_process = fake
    await broker.stop()
    assert fake.terminated is True
    assert broker.status.state == RunState.STOPPED
