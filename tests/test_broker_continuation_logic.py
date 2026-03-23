from __future__ import annotations

import asyncio
from unittest.mock import Mock

import pytest

from cli_orchestrator_ui.broker.engine import BrokerEngine
from cli_orchestrator_ui.broker.models import RunState


@pytest.fixture
def broker():
    events = []

    def sink(event):
        events.append(event)

    return BrokerEngine(sink=sink, codex_cmd=["codex"]), events


def test_build_initial_task_prompt_appends_once(broker) -> None:
    engine, _ = broker
    base = "Do work."
    first = engine._build_initial_task_prompt(base)
    second = engine._build_initial_task_prompt(first)
    assert "consult other models" in first.lower()
    assert "run_status:" in first.lower()
    assert second.count("consult other models") == 1
    assert second.lower().count("when you finish each run") == 1


def test_select_continuation_prompt_paths(broker) -> None:
    engine, _ = broker

    engine._last_task_text = "small task"
    assert "do not restart" in engine._select_continuation_prompt().lower()

    engine._last_task_text = "phase 1 then step 2 then refactor"
    assert "until the task is fully complete" in engine._select_continuation_prompt().lower()

    engine._saw_partial_since_continue = True
    assert "not finished yet" in engine._select_continuation_prompt().lower()
    engine._saw_partial_since_continue = False

    engine._saw_stall_signal = True
    assert "if you are uncertain or stuck" in engine._select_continuation_prompt().lower()
    engine._saw_stall_signal = False

    engine._test_failure_streak = engine._TEST_FAILURE_ESCALATION_THRESHOLD
    assert "repeated test failures" in engine._select_continuation_prompt().lower()


def test_update_line_observations_and_failure_trend(broker) -> None:
    engine, _ = broker
    engine._update_line_observations("remaining step: not finished", "stdout")
    assert engine._saw_partial_since_continue is True

    engine._update_line_observations("Traceback - 3 failed", "stderr")
    assert engine._last_failed_count == 3
    assert engine._test_failure_streak >= 1

    engine._update_line_observations("completed successfully", "stdout")
    assert engine._saw_progress_since_continue is True
    assert engine._no_progress_cycles == 0


def test_extract_failed_count_variants(broker) -> None:
    engine, _ = broker
    assert engine._extract_failed_test_count("2 failed, 10 passed") == 2
    assert engine._extract_failed_test_count("failed: 5") == 5
    assert engine._extract_failed_test_count("failures: 8") == 8
    assert engine._extract_failed_test_count("all green") is None


def test_track_test_failure_trend_paths(broker) -> None:
    engine, _ = broker
    engine._track_test_failure_trend(None)
    assert engine._test_failure_streak == 1

    engine._track_test_failure_trend(4)
    assert engine._best_failed_count == 4
    assert engine._test_failure_streak == 0

    engine._track_test_failure_trend(5)
    assert engine._test_failure_streak == 1

    engine._track_test_failure_trend(3)
    assert engine._best_failed_count == 3
    assert engine._test_failure_streak == 0


@pytest.mark.asyncio
async def test_handle_state_specific_actions_and_journal(broker) -> None:
    engine, events = broker
    engine.auto_continue = True
    engine.status.state = RunState.INCOMPLETE
    engine._saw_progress_since_continue = False
    schedule = Mock()
    engine._schedule_auto_continue = schedule
    engine._handle_state_specific_actions("incomplete")
    schedule.assert_called_once_with("incomplete_output")
    assert engine._no_progress_cycles == 1

    engine.status.state = RunState.BLOCKED
    engine._handle_state_specific_actions("Need your input?")
    assert "operator" in engine.status.summary.lower()

    engine.status.state = RunState.DONE
    task = asyncio.create_task(asyncio.sleep(10))
    engine._auto_continue_task = task
    engine._process = type("P", (), {"returncode": None})()
    gate = Mock()
    engine._schedule_completion_gate = gate
    engine._handle_state_specific_actions("done")
    await asyncio.sleep(0)
    assert task.cancelled() is True
    gate.assert_called_once_with("done_output")

    engine.status.loop_count = 2
    engine._write_journal_snapshot()
    assert any("journal snapshot" in evt.message.lower() for evt in events)


@pytest.mark.asyncio
async def test_auto_continue_after_delay_exception_sets_failed(broker) -> None:
    engine, events = broker
    engine.auto_continue_delay_s = 0.0

    async def boom():
        raise RuntimeError("x")

    engine.continue_task = boom  # type: ignore[assignment]
    await engine._auto_continue_after_delay()
    assert engine.status.state == RunState.FAILED
    assert any("auto-continue failed" in evt.message.lower() for evt in events)


@pytest.mark.asyncio
async def test_run_status_continue_schedules_auto_continue(broker) -> None:
    engine, _ = broker
    engine.auto_continue = True
    engine.auto_continue_delay_s = 0.0
    resume = Mock()
    engine._schedule_auto_continue = resume
    handled = engine._maybe_apply_run_status("RUN_STATUS:CONTINUE")
    assert handled is True
    assert engine.status.state == RunState.INCOMPLETE
    resume.assert_called_once_with("run_status_continue")
