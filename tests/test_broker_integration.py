from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from cli_orchestrator_ui.broker.engine import BrokerEngine
from cli_orchestrator_ui.broker.models import AgentName, BrokerEvent, RunState, TaskMode


FIXTURE = Path(__file__).parent / "fixtures" / "fake_agent.py"


async def _wait_for_event(
    queue: asyncio.Queue[BrokerEvent],
    predicate,
    timeout: float = 5.0,
) -> BrokerEvent:
    async def _inner() -> BrokerEvent:
        while True:
            evt = await queue.get()
            if predicate(evt):
                return evt

    return await asyncio.wait_for(_inner(), timeout=timeout)


@pytest.fixture
def event_queue() -> asyncio.Queue[BrokerEvent]:
    return asyncio.Queue()


@pytest.fixture
def sink(event_queue: asyncio.Queue[BrokerEvent]):
    def _sink(event: BrokerEvent) -> None:
        event_queue.put_nowait(event)

    return _sink


@pytest.fixture(autouse=True)
def disable_pty(monkeypatch: pytest.MonkeyPatch):
    # Integration fixture agent uses stdio pipes deterministically.
    monkeypatch.setenv("BROKER_PTY", "0")


@pytest.mark.asyncio
async def test_done_flow_real_subprocess(sink, event_queue: asyncio.Queue[BrokerEvent]) -> None:
    broker = BrokerEngine(sink=sink, codex_cmd=[sys.executable, str(FIXTURE), "--mode", "done"])
    try:
        await broker.start("run a test", TaskMode.CODEX_ONLY)
        await _wait_for_event(event_queue, lambda e: "processing complete" in e.message.lower())
        assert broker._wait_task is not None
        await asyncio.wait_for(broker._wait_task, timeout=5.0)
        assert broker.status.state == RunState.DONE
    finally:
        await broker.shutdown()


@pytest.mark.asyncio
async def test_continue_flow_real_subprocess(sink, event_queue: asyncio.Queue[BrokerEvent]) -> None:
    broker = BrokerEngine(sink=sink, codex_cmd=[sys.executable, str(FIXTURE), "--mode", "continue"])
    try:
        await broker.start("run a test", TaskMode.CODEX_ONLY)
        await _wait_for_event(event_queue, lambda e: "waiting for input" in e.message.lower())
        assert broker.status.state == RunState.INCOMPLETE

        await broker.continue_task()
        await _wait_for_event(event_queue, lambda e: "continuation prompt sent" in e.message.lower())
        await _wait_for_event(event_queue, lambda e: "completed" in e.message.lower())
        assert broker._wait_task is not None
        await asyncio.wait_for(broker._wait_task, timeout=5.0)
        assert broker.status.state == RunState.DONE
        assert broker.status.loop_count == 1
    finally:
        await broker.shutdown()


@pytest.mark.asyncio
async def test_tty_required_detection(sink, event_queue: asyncio.Queue[BrokerEvent]) -> None:
    broker = BrokerEngine(sink=sink, codex_cmd=[sys.executable, str(FIXTURE), "--mode", "tty"])
    try:
        await broker.start("run a test", TaskMode.CODEX_ONLY)
        await _wait_for_event(event_queue, lambda e: "stdin is not a terminal" in e.message.lower())
        await _wait_for_event(event_queue, lambda e: "requires a terminal" in e.message.lower())
        assert broker.status.state == RunState.BLOCKED
        assert "tty" in broker.status.summary.lower()
    finally:
        await broker.shutdown()


@pytest.mark.asyncio
async def test_negative_guards_no_active_process(sink, event_queue: asyncio.Queue[BrokerEvent]) -> None:
    broker = BrokerEngine(sink=sink, codex_cmd=[sys.executable, str(FIXTURE), "--mode", "done"])
    try:
        await broker.continue_task()
        evt = await _wait_for_event(event_queue, lambda e: "no active process to continue" in e.message.lower())
        assert evt.source == AgentName.BROKER

        await broker.stop()
        await _wait_for_event(event_queue, lambda e: "no active process to stop" in e.message.lower())

        await broker.retry()
        await _wait_for_event(event_queue, lambda e: "no previous task to retry" in e.message.lower())
    finally:
        await broker.shutdown()


@pytest.mark.asyncio
async def test_continue_after_exit_does_not_spawn_new_session(sink, event_queue: asyncio.Queue[BrokerEvent]) -> None:
    broker = BrokerEngine(sink=sink, codex_cmd=[sys.executable, str(FIXTURE), "--mode", "resume"])
    try:
        await broker.start("run task", TaskMode.CODEX_ONLY)
        await _wait_for_event(event_queue, lambda e: "completed" in e.message.lower())
        assert broker._wait_task is not None
        await asyncio.wait_for(broker._wait_task, timeout=5.0)
        assert broker.status.state == RunState.DONE

        prev_loop = broker.status.loop_count
        await broker.continue_task()
        await _wait_for_event(event_queue, lambda e: "no active process to continue" in e.message.lower())
        assert broker.status.loop_count == prev_loop
    finally:
        await broker.shutdown()
