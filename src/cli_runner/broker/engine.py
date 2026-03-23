from __future__ import annotations

import asyncio
import os
import re
import shlex
import shutil
import subprocess
from asyncio.subprocess import Process
from collections import deque
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path

from cli_runner.broker.codexmem import CodexMemBridge
from cli_runner.broker.models import AgentName, BrokerEvent, BrokerStatus, RunState, TaskMode


EventSink = Callable[[BrokerEvent], None]

# Matches ANSI escape sequences (colors, cursor movement, etc.)
# More comprehensive regex to handle OSC, character sets, and complex PTY sequences.
_ANSI_RE = re.compile(
    r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[\(\)].|[P^_][^\x1b]*\x1b\\|[#%&*+./].|[@-Z\\-_])"
)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0B-\x1F\x7F]")
_TERMINAL_COMPLETION_PATTERNS = (
    "nothing else to do",
    "no further action required",
    "task fully complete",
)
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
_PARTIAL_OUTPUT_PATTERNS = (
    "not finished",
    "remaining",
    "next step",
    "next phase",
    "left off",
    "todo",
    "still need",
)
_STALL_PATTERNS = (
    "stuck",
    "uncertain",
    "not sure",
    "can't proceed",
    "cannot proceed",
)
_TEST_FAILURE_PATTERNS = (
    "test failed",
    "tests failed",
    "assertionerror",
    "traceback",
    "failing test",
    "regression",
)
_COMPLETION_DECISION_RE = re.compile(r"\bdecision\s*:\s*(done|continue|rework)\b", re.IGNORECASE)
_COMPLETION_GATE_PROMPT = (
    "Reply with exactly one token: DECISION:DONE or DECISION:CONTINUE or DECISION:REWORK."
)
_RUN_STATUS_RE = re.compile(r"\brun_status\s*:\s*(done|continue|rework)\b", re.IGNORECASE)
_RUN_STATUS_INSTRUCTION = (
    "When you finish each run, include exactly one final line: RUN_STATUS:DONE or RUN_STATUS:CONTINUE or RUN_STATUS:REWORK."
)

def _contains_phrase(text: str, phrase: str) -> bool:
    """Match phrase on token boundaries to avoid substring false positives (e.g. 'unblocked')."""
    return re.search(rf"\b{re.escape(phrase)}\b", text) is not None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def strip_ansi(text: str) -> str:
    """Removes ANSI escape sequences and carriage returns to stabilize UI logs."""
    if not isinstance(text, str):
        if isinstance(text, bytes):
            text = text.decode("utf-8", errors="replace")
        else:
            text = str(text)
    # 1. Remove ANSI escape sequences
    text = _ANSI_RE.sub("", text)
    # 2. Remove carriage returns which cause overwriting/flicker in many log widgets
    text = text.replace("\r", "")
    # 3. Remove other C0 control characters that can corrupt text UI rendering.
    text = _CONTROL_CHAR_RE.sub("", text)
    return text


def _parse_cmd(raw: str) -> list[str]:
    return shlex.split(raw, posix=False)


def _resolve_command(cmd: list[str]) -> list[str]:
    if not cmd:
        return cmd
    program = cmd[0]
    if os.path.isabs(program) and os.path.exists(program):
        return cmd
    if os.name == "nt" and "." not in os.path.basename(program):
        # Prefer shell wrappers for extensionless commands on Windows.
        # Some tools expose a broken .exe shim while their .cmd wrapper works.
        for ext in (".cmd", ".bat", ".exe"):
            candidate = shutil.which(program + ext)
            if candidate:
                return [candidate, *cmd[1:]]
    resolved = shutil.which(program)
    if resolved:
        return [resolved, *cmd[1:]]
    return cmd


def derive_state_from_output(line: str, current: RunState) -> RunState:
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


def is_terminal_completion_signal(line: str) -> bool:
    lowered = line.lower()
    return any(pattern in lowered for pattern in _TERMINAL_COMPLETION_PATTERNS)


def _should_use_pty_for_command(cmd: list[str]) -> bool:
    if os.name != "nt" or not cmd:
        return False
    force = os.environ.get("BROKER_PTY", "").strip().lower()
    if force in {"1", "true", "yes"}:
        return True
    if force in {"0", "false", "no", "off"}:
        return False
    # Default on Windows for Codex CLI because it often requires a TTY stdin.
    base = os.path.basename(cmd[0]).lower()
    return base in {"codex", "codex.cmd", "codex.exe"}


class BrokerEngine:
    """Deterministic-first broker core for Phase 1."""
    _REPEAT_OUTPUT_THRESHOLD = 3
    _NO_PROGRESS_THRESHOLD = 2
    _TEST_FAILURE_ESCALATION_THRESHOLD = 2
    _MAX_IDENTICAL_CONTINUE_THRESHOLD = 4

    def __init__(
        self,
        sink: EventSink,
        codex_cmd: str | Sequence[str] | None = None,
    ):
        self._sink = sink
        self.status = BrokerStatus()
        self._lock = asyncio.Lock()
        self._process: Process | None = None
        self._stdout_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._wait_task: asyncio.Task[None] | None = None
        self._auto_continue_task: asyncio.Task[None] | None = None
        self._completion_gate_task: asyncio.Task[None] | None = None
        self._completion_gate_pending = False
        self._pty_initial_task: str | None = None
        self._pty_initial_task_sending = False
        self._pty_task_injected = False
        self._pty_queue_commit_sent = False
        self._pty_commit_nudge_task: asyncio.Task[None] | None = None
        self._pty_inject_watchdog_task: asyncio.Task[None] | None = None
        self._pty_process = None
        self._active_command: list[str] = []
        self._uses_stdin_session = True
        self._saw_terminal_completion_signal = False
        self._last_task_text = ""
        self._continue_prompt_history: deque[str] = deque(maxlen=8)
        self._recent_output_lines: deque[str] = deque(maxlen=20)
        self._repeat_output_streak = 0
        self._no_progress_cycles = 0
        self._saw_progress_since_continue = False
        self._saw_partial_since_continue = False
        self._saw_stall_signal = False
        self._test_failure_streak = 0
        self._best_failed_count: int | None = None
        self._last_failed_count: int | None = None
        self._last_action_summary = "idle"
        self._escalation_hint_used = False
        self._log_dir = self._init_log_dir()
        self._log_path = self._log_dir / "broker.log"
        self._codex_journal_path = self._log_dir / "codex_journal.log"
        self._run_cwd = Path.cwd()
        self._codex_mem = CodexMemBridge(
            cwd=self._run_cwd,
            repo_id=self._run_cwd.name,
            branch=self._detect_git_branch(self._run_cwd),
        )
        self._last_memory_signature: tuple[str, str] | None = None
        auto_continue_raw = os.environ.get("AUTO_CONTINUE", "1").strip().lower()
        self.auto_continue = auto_continue_raw not in {"0", "false", "no", "off"}
        self.max_auto_loops = int(os.environ.get("AUTO_MAX_LOOPS", "25"))
        self.auto_continue_delay_s = float(os.environ.get("AUTO_CONTINUE_DELAY", "1.0"))
        self.completion_gate_delay_s = float(os.environ.get("COMPLETION_GATE_DELAY", "0.4"))
        self.pty_initial_send_delay_s = float(os.environ.get("BROKER_PTY_INITIAL_SEND_DELAY", "0.6"))
        self.pty_initial_inject_max_wait_s = float(os.environ.get("BROKER_PTY_INITIAL_INJECT_MAX_WAIT", "8.0"))
        self.pty_commit_nudge_delay_s = float(os.environ.get("BROKER_PTY_COMMIT_NUDGE_DELAY", "1.2"))
        self._pty_prompt_ready = asyncio.Event()

        self.codex_cmd = _resolve_command(self._coerce_cmd(codex_cmd or os.environ.get("CODEX_CMD", "codex")))

    @staticmethod
    def _coerce_cmd(raw: str | Sequence[str]) -> list[str]:
        if isinstance(raw, str):
            return _parse_cmd(raw)
        return [str(part) for part in raw]

    @staticmethod
    def _init_log_dir() -> Path:
        override = os.environ.get("BROKER_LOG_DIR", "").strip()
        if override:
            logs_dir = Path(override).expanduser()
        else:
            # Resolve to project-root/logs for deterministic troubleshooting.
            logs_dir = Path(__file__).resolve().parents[3] / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        return logs_dir

    @staticmethod
    def _detect_git_branch(cwd: Path) -> str:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(cwd),
                text=True,
                capture_output=True,
                timeout=1.5,
                check=False,
            )
        except Exception:
            return "unknown"
        if result.returncode != 0:
            return "unknown"
        branch = result.stdout.strip()
        return branch or "unknown"

    @property
    def log_path(self) -> Path:
        return self._log_path

    @property
    def codex_journal_path(self) -> Path:
        return self._codex_journal_path

    async def preload_memory_journal_lines(self, limit: int, max_chars: int) -> list[str]:
        return await self._codex_mem.load_recent_lines(limit=limit, max_chars=max_chars)

    async def start(self, task_text: str, mode: TaskMode) -> None:
        async with self._lock:
            if self._process and self._process.returncode is None:
                self._emit(AgentName.BROKER, "Task already running. Stop it before starting another.")
                return
            if not task_text.strip():
                self._emit(AgentName.BROKER, "Task text is empty. Paste a task first.")
                return

            self._reset_run_tracking()
            prepared_task = self._build_initial_task_prompt(task_text)
            self._last_task_text = prepared_task
            self.status.mode = mode
            self.status.state = RunState.RUNNING
            self.status.active_agent = AgentName.CODEX
            self.status.summary = "Codex launched"
            self.status.last_update_utc = _utc_now()
            self._emit(AgentName.BROKER, f"Starting Codex in mode={mode.value}.")
            self._record_memory_run(summary="Codex run started.", status="running")
            await self._spawn_codex(prepared_task)

    async def continue_task(self) -> None:
        async with self._lock:
            has_active = (
                (self._process and self._process.returncode is None)
                or (self._pty_process and self._pty_process.isalive())
            )
            if not has_active:
                self._emit(
                    AgentName.BROKER,
                    "No active process to continue. Continue only works on a live Codex session.",
                )
                return
            if not self._uses_stdin_session:
                self._emit(
                    AgentName.BROKER,
                    "Continue unavailable: active command is not stdin-driven.",
                )
                return
            if self.status.loop_count >= self.max_auto_loops:
                self.status.state = RunState.PAUSED
                self.status.summary = f"Iteration limit reached ({self.max_auto_loops})."
                self.status.last_update_utc = _utc_now()
                self._emit(AgentName.BROKER, self.status.summary)
                self._emit(AgentName.BROKER, "Loop safety triggered: awaiting operator action.")
                return
            if self._is_hard_blocked_state():
                self._emit(
                    AgentName.BROKER,
                    "State is blocked. Waiting for operator input before continuing.",
                )
                return
            if self.status.state == RunState.DONE:
                self._emit(AgentName.BROKER, "Task already marked done; no continuation sent.")
                return

            prompt = self._select_continuation_prompt()
            await self._send_stdin(prompt + "\n")
            self.status.loop_count += 1
            self._completion_gate_pending = False
            self.status.state = RunState.RUNNING
            self.status.summary = f"Continuation prompt sent (loop={self.status.loop_count})"
            self.status.last_update_utc = _utc_now()
            self._emit(AgentName.BROKER, self.status.summary)
            self._continue_prompt_history.append(prompt)
            self._saw_progress_since_continue = False
            self._saw_partial_since_continue = False
            self._write_journal_snapshot()

    async def stop(self) -> None:
        async with self._lock:
            if self._auto_continue_task and not self._auto_continue_task.done():
                self._auto_continue_task.cancel()
                self._auto_continue_task = None
            if self._completion_gate_task and not self._completion_gate_task.done():
                self._completion_gate_task.cancel()
                self._completion_gate_task = None
            if self._pty_inject_watchdog_task and not self._pty_inject_watchdog_task.done():
                self._pty_inject_watchdog_task.cancel()
                self._pty_inject_watchdog_task = None
            if self._pty_commit_nudge_task and not self._pty_commit_nudge_task.done():
                self._pty_commit_nudge_task.cancel()
                self._pty_commit_nudge_task = None
            self._completion_gate_pending = False
            if (
                (not self._process or self._process.returncode is not None)
                and (not self._pty_process or not self._pty_process.isalive())
            ):
                self._emit(AgentName.BROKER, "No active process to stop.")
                return
            self._emit(AgentName.BROKER, "Stopping active process...")
            if self._pty_process and self._pty_process.isalive():
                self._pty_process.terminate(force=True)
            elif self._process:
                self._process.terminate()
            self._pty_prompt_ready.clear()
            self._pty_initial_task = None
            self._pty_initial_task_sending = False
            self._pty_task_injected = False
            self.status.state = RunState.STOPPED
            self.status.summary = "Stop requested."
            self.status.last_update_utc = _utc_now()
            self._record_memory_run(summary=self.status.summary, status="stopped")

    def emergency_stop(self) -> None:
        """Best-effort synchronous stop for signal-handler style exits."""
        if self._auto_continue_task and not self._auto_continue_task.done():
            self._auto_continue_task.cancel()
            self._auto_continue_task = None
        if self._completion_gate_task and not self._completion_gate_task.done():
            self._completion_gate_task.cancel()
            self._completion_gate_task = None
        if self._pty_inject_watchdog_task and not self._pty_inject_watchdog_task.done():
            self._pty_inject_watchdog_task.cancel()
            self._pty_inject_watchdog_task = None
        if self._pty_commit_nudge_task and not self._pty_commit_nudge_task.done():
            self._pty_commit_nudge_task.cancel()
            self._pty_commit_nudge_task = None
        self._completion_gate_pending = False
        if self._pty_process:
            try:
                if self._pty_process.isalive():
                    self._pty_process.terminate(force=True)
            except Exception:
                pass
        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
            except Exception:
                pass
        self._pty_prompt_ready.clear()
        self._pty_initial_task = None
        self._pty_initial_task_sending = False
        self._pty_task_injected = False
        self.status.state = RunState.STOPPED
        self.status.summary = "Emergency stop requested."
        self.status.last_update_utc = _utc_now()
        self._record_memory_run(summary=self.status.summary, status="stopped")

    async def shutdown(self) -> None:
        """Best-effort cleanup for tests and app shutdown."""
        await self.stop()
        tasks = [
            task
            for task in (
                self._stdout_task,
                self._stderr_task,
                self._wait_task,
                self._auto_continue_task,
                self._completion_gate_task,
                self._pty_inject_watchdog_task,
                self._pty_commit_nudge_task,
            )
            if task
        ]
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def retry(self) -> None:
        async with self._lock:
            if not self._last_task_text.strip():
                self._emit(AgentName.BROKER, "No previous task to retry.")
                return
        await self.stop()
        await asyncio.sleep(0.2)
        await self.start(self._last_task_text, self.status.mode)

    async def escalate(self) -> None:
        async with self._lock:
            self._emit(
                AgentName.BROKER,
                "Escalation requested. Surface intervention and continue Codex-focused handling.",
            )
            self.status.summary = "Escalate requested."
            self.status.last_update_utc = _utc_now()
            self._record_memory_run(summary=self.status.summary, status="escalated")

    async def _spawn_codex(self, task_text: str) -> None:
        launch_cmd = self._build_codex_launch_command(task_text)
        self._active_command = launch_cmd
        self._saw_terminal_completion_signal = False
        run_cwd = Path.cwd()
        run_env = self._build_subprocess_env(run_cwd)
        if _should_use_pty_for_command(launch_cmd):
            ok = await self._spawn_codex_pty(task_text)
            if ok:
                return
        try:
            self._process = await asyncio.create_subprocess_exec(
                *launch_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(run_cwd),
                env=run_env,
            )
        except FileNotFoundError:
            self.status.state = RunState.FAILED
            self.status.active_agent = AgentName.BROKER
            self.status.summary = (
                "Codex executable not found. Set CODEX_CMD to an absolute executable path "
                "(for example C:\\Users\\andrew.walsh\\AppData\\Roaming\\npm\\codex.cmd)."
            )
            self.status.last_update_utc = _utc_now()
            self._emit(AgentName.BROKER, self.status.summary)
            return
        except OSError as exc:
            self.status.state = RunState.FAILED
            self.status.active_agent = AgentName.BROKER
            self.status.summary = f"Failed to launch Codex: {exc}"
            self.status.last_update_utc = _utc_now()
            self._emit(AgentName.BROKER, self.status.summary)
            return
        self._emit(AgentName.BROKER, f"Codex PID={self._process.pid}")
        self._stdout_task = asyncio.create_task(self._pump_stream(self._process.stdout, AgentName.CODEX, "stdout"))
        self._stderr_task = asyncio.create_task(self._pump_stream(self._process.stderr, AgentName.CODEX, "stderr"))
        self._wait_task = asyncio.create_task(self._wait_for_exit(self._process))
        if self._uses_stdin_session:
            await self._send_stdin(task_text.strip() + "\n")

    async def _spawn_codex_pty(self, task_text: str) -> bool:
        try:
            from winpty import PtyProcess
        except Exception as exc:
            self._emit(AgentName.BROKER, f"PTY unavailable, falling back to pipes: {exc}")
            return False

        try:
            self._pty_prompt_ready.clear()
            self._pty_initial_task = None
            self._pty_initial_task_sending = False
            self._pty_task_injected = False
            self._pty_queue_commit_sent = False
            self._pty_commit_nudge_task = None
            self._pty_inject_watchdog_task = None
            self._pty_process = PtyProcess.spawn(self._active_command)
        except Exception as exc:
            self._emit(AgentName.BROKER, f"PTY launch failed, falling back to pipes: {exc}")
            self._pty_process = None
            return False

        pid = getattr(self._pty_process, "pid", "unknown")
        self._emit(AgentName.BROKER, f"Codex PTY PID={pid}")
        self._stdout_task = asyncio.create_task(self._pump_pty_stream(AgentName.CODEX, "pty"))
        self._wait_task = asyncio.create_task(self._wait_for_pty_exit())
        if self._uses_stdin_session:
            await self._send_initial_pty_task(task_text)
        return True

    async def _send_initial_pty_task(self, task_text: str) -> None:
        # Queue initial task and submit only after a prompt-ready signal is observed from PTY output.
        self._pty_initial_task = task_text.strip()
        self._emit(AgentName.BROKER, "Initial PTY task queued.")
        self._start_pty_inject_watchdog()
        await self._flush_initial_pty_task_if_ready()

    def _start_pty_inject_watchdog(self) -> None:
        if self.pty_initial_inject_max_wait_s <= 0:
            return
        if self._pty_inject_watchdog_task and not self._pty_inject_watchdog_task.done():
            return
        self._pty_inject_watchdog_task = asyncio.create_task(self._pty_inject_watchdog())

    async def _pty_inject_watchdog(self) -> None:
        try:
            await asyncio.sleep(self.pty_initial_inject_max_wait_s)
            if self._pty_task_injected or not self._pty_initial_task:
                return
            self._emit(AgentName.BROKER, "Initial PTY task watchdog firing; injecting task.")
            await self._flush_initial_pty_task_force()
        except asyncio.CancelledError:
            return

    async def _flush_initial_pty_task_if_ready(self) -> None:
        if not self._pty_prompt_ready.is_set():
            return
        await self._flush_initial_pty_task_force()

    async def _flush_initial_pty_task_force(self) -> None:
        if not self._pty_initial_task:
            return
        if self._pty_initial_task_sending:
            return
        self._pty_initial_task_sending = True
        task_text = self._pty_initial_task
        try:
            if self.pty_initial_send_delay_s > 0:
                await asyncio.sleep(self.pty_initial_send_delay_s)
            sent = await self._send_pty_submit(task_text)
            if sent:
                self._pty_initial_task = None
                self._pty_task_injected = True
                self._emit(AgentName.BROKER, "Initial PTY task sent.")
                if self._pty_inject_watchdog_task and not self._pty_inject_watchdog_task.done():
                    self._pty_inject_watchdog_task.cancel()
                    self._pty_inject_watchdog_task = None
                if self.pty_commit_nudge_delay_s > 0:
                    self._start_pty_commit_nudge()
        finally:
            self._pty_initial_task_sending = False

    def _start_pty_commit_nudge(self) -> None:
        if self._pty_commit_nudge_task and not self._pty_commit_nudge_task.done():
            return
        self._pty_commit_nudge_task = asyncio.create_task(self._pty_commit_nudge())

    async def _pty_commit_nudge(self) -> None:
        try:
            await asyncio.sleep(self.pty_commit_nudge_delay_s)
            if not self._pty_task_injected:
                return
            if self._pty_queue_commit_sent:
                return
            self._pty_queue_commit_sent = True
            self._emit(AgentName.BROKER, "Sending initial prompt commit nudge.")
            await self._send_pty_submit("")
        except asyncio.CancelledError:
            return

    async def _send_pty_submit(self, text: str) -> bool:
        if not self._pty_process:
            return False
        payload = f"{text}\r\n" if text else "\r\n"
        try:
            await asyncio.to_thread(self._pty_process.write, payload)
            return True
        except Exception:
            return False

    @staticmethod
    def _looks_like_pty_prompt_ready(line: str) -> bool:
        stripped = line.strip()
        lowered = line.lower()
        if "openai codex" in lowered and "directory:" in lowered:
            return True
        if "/model to change" in lowered:
            return True
        if "use /skills to list available skills" in lowered:
            return True
        if stripped.endswith("›"):
            return True
        return False

    @staticmethod
    def _is_codex_binary(cmd: list[str]) -> bool:
        if not cmd:
            return False
        base = os.path.basename(cmd[0]).lower()
        return base in {"codex", "codex.cmd", "codex.exe"}

    def _build_codex_launch_command(self, task_text: str) -> list[str]:
        self._uses_stdin_session = True
        return self.codex_cmd

    @staticmethod
    def _build_subprocess_env(cwd: Path) -> dict[str, str]:
        env = dict(os.environ)
        env["PYTHONUTF8"] = "1"
        # Long-term default: use caller/global environment, not an implicit project venv.
        return env

    async def _send_stdin(self, payload: str) -> None:
        if self._pty_process and self._pty_process.isalive():
            normalized = payload.replace("\n", "\r\n")
            await asyncio.to_thread(self._pty_process.write, normalized)
            return
        if not self._process or not self._process.stdin:
            return
        self._process.stdin.write(payload.encode("utf-8", errors="ignore"))
        await self._process.stdin.drain()

    async def _wait_for_pty_exit(self) -> None:
        if not self._pty_process:
            return
        return_code = await asyncio.to_thread(self._pty_process.wait)
        if return_code == 0 and self._completion_gate_pending:
            self._completion_gate_pending = False
            self.status.state = RunState.PAUSED
            self.status.summary = "PTY exited before completion decision; operator review required."
        if return_code == 0 and self.status.state == RunState.BLOCKED and not self._is_hard_blocked_state():
            self.status.state = RunState.INCOMPLETE
            self.status.summary = "PTY process exited after input prompt; continuation needed."
        elif return_code == 0 and self.status.state not in (RunState.STOPPED, RunState.DONE, RunState.BLOCKED, RunState.PAUSED, RunState.INCOMPLETE):
            self.status.state = RunState.DONE
            self.status.summary = "PTY process exited successfully."
        elif return_code != 0 and self.status.state not in (RunState.STOPPED, RunState.BLOCKED):
            self.status.state = RunState.FAILED
            self.status.summary = f"PTY process exited with code {return_code}."
        self.status.active_agent = AgentName.BROKER
        self.status.last_update_utc = _utc_now()
        self._emit(AgentName.BROKER, self.status.summary)
        self._record_memory_run(summary=self.status.summary, status=self.status.state.value)

    async def _wait_for_exit(self, process: Process) -> None:
        return_code = await process.wait()
        if return_code == 0 and self._completion_gate_pending:
            self._completion_gate_pending = False
            self.status.state = RunState.PAUSED
            self.status.summary = "Process exited before completion decision; operator review required."
        if return_code == 0 and self.status.state == RunState.BLOCKED and not self._is_hard_blocked_state():
            self.status.state = RunState.INCOMPLETE
            self.status.summary = "Process exited after input prompt; continuation needed."
        elif return_code == 0 and self.status.state not in (RunState.STOPPED, RunState.DONE, RunState.BLOCKED, RunState.PAUSED, RunState.INCOMPLETE):
            self.status.state = RunState.DONE
            self.status.summary = "Process exited successfully."
        elif return_code != 0 and self.status.state not in (RunState.STOPPED, RunState.BLOCKED):
            self.status.state = RunState.FAILED
            self.status.summary = f"Process exited with code {return_code}."
        self.status.active_agent = AgentName.BROKER
        self.status.last_update_utc = _utc_now()
        self._emit(AgentName.BROKER, self.status.summary)
        self._record_memory_run(summary=self.status.summary, status=self.status.state.value)

    def _schedule_auto_continue(self, reason: str) -> None:
        if not self.auto_continue:
            return
        if self.status.loop_count >= self.max_auto_loops:
            self.status.state = RunState.PAUSED
            self.status.summary = f"Auto-continue limit reached ({self.max_auto_loops})."
            self.status.last_update_utc = _utc_now()
            self._emit(AgentName.BROKER, self.status.summary)
            return
        if not self._can_auto_continue():
            return
        if self._auto_continue_task and not self._auto_continue_task.done():
            return
        self._emit(
            AgentName.BROKER,
            f"Auto-continue armed after {reason}; next attempt in {self.auto_continue_delay_s:.1f}s.",
        )
        self._auto_continue_task = asyncio.create_task(self._auto_continue_after_delay())

    def _can_auto_continue(self) -> bool:
        if not self._is_codex_binary(self.codex_cmd):
            self._emit(AgentName.BROKER, "Auto-continue skipped: active command is not Codex.")
            return False
        has_active = (
            (self._process and self._process.returncode is None)
            or (self._pty_process and self._pty_process.isalive())
        )
        if not has_active:
            self._emit(AgentName.BROKER, "Auto-continue skipped: no active Codex session.")
            return False
        if self.status.state == RunState.BLOCKED:
            # Soft-blocked Codex prompts can be resumed automatically.
            # Hard TTY/terminal failures must stop and require operator intervention.
            if self._is_hard_blocked_state():
                self._emit(AgentName.BROKER, "Auto-continue skipped: state is blocked (terminal required).")
                return False
            self._emit(AgentName.BROKER, "Auto-continue proceeding: state is soft-blocked.")
            return True
        if self.status.state in {RunState.PAUSED, RunState.STOPPED, RunState.FAILED}:
            self._emit(AgentName.BROKER, f"Auto-continue skipped: state is {self.status.state.value}.")
            return False
        if self.status.state == RunState.DONE:
            self._emit(AgentName.BROKER, "Auto-continue skipped: task is done.")
            return False
        if self._saw_terminal_completion_signal:
            self._emit(AgentName.BROKER, "Auto-continue skipped: terminal completion signal detected.")
            return False
        return True

    async def _auto_continue_after_delay(self) -> None:
        try:
            await asyncio.sleep(self.auto_continue_delay_s)
            await self.continue_task()
        except asyncio.CancelledError:
            return
        except Exception as exc:
            self.status.state = RunState.FAILED
            self.status.summary = f"Auto-continue failed: {exc}"
            self.status.last_update_utc = _utc_now()
            self._emit(AgentName.BROKER, self.status.summary)

    def _schedule_completion_gate(self, reason: str) -> None:
        if self._completion_gate_pending:
            return
        if not self._can_request_completion_gate():
            return
        if self._completion_gate_task and not self._completion_gate_task.done():
            return
        self._completion_gate_pending = True
        self._emit(
            AgentName.BROKER,
            f"Completion gate armed after {reason}; asking Codex for explicit decision.",
        )
        self._completion_gate_task = asyncio.create_task(self._request_completion_gate_after_delay())

    def _can_request_completion_gate(self) -> bool:
        if self._pty_process is not None:
            return False
        if not self._uses_stdin_session:
            return False
        if not self._is_codex_binary(self.codex_cmd):
            return False
        has_active = (
            (self._process and self._process.returncode is None)
            or (self._pty_process and self._pty_process.isalive())
        )
        return bool(has_active)

    async def _request_completion_gate_after_delay(self) -> None:
        try:
            if self.completion_gate_delay_s > 0:
                await asyncio.sleep(self.completion_gate_delay_s)
            if not self._can_request_completion_gate():
                self._completion_gate_pending = False
                return
            await self._send_stdin(_COMPLETION_GATE_PROMPT + "\n")
            self.status.state = RunState.INCOMPLETE
            self.status.summary = "Completion check requested from Codex."
            self.status.last_update_utc = _utc_now()
            self._emit(AgentName.BROKER, self.status.summary)
        except asyncio.CancelledError:
            self._completion_gate_pending = False
            return
        except Exception as exc:
            self._completion_gate_pending = False
            self.status.state = RunState.PAUSED
            self.status.summary = f"Completion check failed: {exc}"
            self.status.last_update_utc = _utc_now()
            self._emit(AgentName.BROKER, self.status.summary)

    def _extract_completion_decision(self, line: str) -> str | None:
        match = _COMPLETION_DECISION_RE.search(line)
        if not match:
            return None
        return match.group(1).lower()

    def _extract_run_status(self, line: str) -> str | None:
        match = _RUN_STATUS_RE.search(line)
        if not match:
            return None
        return match.group(1).lower()

    def _maybe_apply_run_status(self, line: str) -> bool:
        run_status = self._extract_run_status(line)
        if not run_status:
            return False
        if run_status == "done":
            self.status.state = RunState.DONE
            self.status.summary = "Run status: done."
            self._last_action_summary = "run_status:done"
            if self._auto_continue_task and not self._auto_continue_task.done():
                self._auto_continue_task.cancel()
        elif run_status == "continue":
            self.status.state = RunState.INCOMPLETE
            self.status.summary = "Run status: continue."
            self._last_action_summary = "run_status:continue"
            if self.auto_continue:
                self._schedule_auto_continue("run_status_continue")
        else:
            self.status.state = RunState.PAUSED
            self.status.summary = "Run status: rework requested."
            self._last_action_summary = "run_status:rework"
        self._emit(AgentName.BROKER, self.status.summary)
        return True

    def _maybe_apply_completion_decision(self, line: str) -> bool:
        if not self._completion_gate_pending:
            return False
        decision = self._extract_completion_decision(line)
        if not decision:
            return False
        self._completion_gate_pending = False
        if decision == "done":
            self.status.state = RunState.DONE
            self.status.summary = "Completion gate decision: done."
            self._last_action_summary = "completion_gate:done"
        elif decision == "continue":
            self.status.state = RunState.INCOMPLETE
            self.status.summary = "Completion gate decision: continue."
            self._last_action_summary = "completion_gate:continue"
            if self.auto_continue:
                self._schedule_auto_continue("completion_gate_continue")
        else:
            self.status.state = RunState.PAUSED
            self.status.summary = "Completion gate decision: rework requested."
            self._last_action_summary = "completion_gate:rework"
        self._emit(AgentName.BROKER, self.status.summary)
        return True

    def _reset_run_tracking(self) -> None:
        self._continue_prompt_history.clear()
        self._recent_output_lines.clear()
        self._repeat_output_streak = 0
        self._no_progress_cycles = 0
        self._saw_progress_since_continue = False
        self._saw_partial_since_continue = False
        self._saw_stall_signal = False
        self._test_failure_streak = 0
        self._best_failed_count = None
        self._last_failed_count = None
        self._last_action_summary = "task_started"
        self._escalation_hint_used = False
        self._pty_prompt_ready.clear()
        self._pty_initial_task = None
        self._pty_initial_task_sending = False
        self._pty_task_injected = False
        self._pty_queue_commit_sent = False
        if self._pty_commit_nudge_task and not self._pty_commit_nudge_task.done():
            self._pty_commit_nudge_task.cancel()
        self._pty_commit_nudge_task = None
        if self._pty_inject_watchdog_task and not self._pty_inject_watchdog_task.done():
            self._pty_inject_watchdog_task.cancel()
        self._pty_inject_watchdog_task = None

    def _build_initial_task_prompt(self, task_text: str) -> str:
        suffix = "You may consult other models for architecture, critique, validation, or debugging if needed."
        trimmed = task_text.strip()
        lowered = trimmed.lower()
        parts: list[str] = [trimmed]
        if suffix.lower() not in lowered:
            parts.append(suffix)
        if "run_status:" not in lowered:
            parts.append(_RUN_STATUS_INSTRUCTION)
        if len(parts) == 1:
            return trimmed
        return "\n\n".join(parts)

    def _select_continuation_prompt(self) -> str:
        escalate_test_failures = self._should_escalate_test_failures()
        stalling = self._is_stalling()
        if escalate_test_failures:
            self._escalation_hint_used = True
            self._last_action_summary = "escalation_hint:test_failures"
            return (
                "You appear to be stuck on repeated test failures or debugging churn. "
                "Before continuing blindly, consider consulting another model for debugging, critique, or an alternative approach."
            )
        if stalling:
            self._escalation_hint_used = True
            self._last_action_summary = "escalation_hint:stalling"
            return (
                "Continue. If you are uncertain or stuck, reconsider your approach and proceed. Do not restart. "
                "If you need a second opinion, debugging help, or validation, consider consulting other models."
            )
        if self._saw_partial_since_continue:
            self._last_action_summary = "continue:partial_output"
            return "Continue. You have not finished yet. Complete the remaining steps."
        if self._is_long_or_multistage_task():
            self._last_action_summary = "continue:multistage"
            return (
                "Continue exactly where you left off. Proceed to the next step and continue until the task is fully complete."
            )
        self._last_action_summary = "continue:default"
        return "Continue exactly where you left off. Do not restart. Complete the next step."

    def _is_long_or_multistage_task(self) -> bool:
        lowered = self._last_task_text.lower()
        if len(lowered) > 1200:
            return True
        markers = ("phase", "step", "multi-stage", "milestone", "plan", "refactor", "then")
        return sum(1 for token in markers if token in lowered) >= 2

    def _is_stalling(self) -> bool:
        repeated_prompt = False
        if self._continue_prompt_history:
            repeated_prompt = self._continue_prompt_history.count(self._continue_prompt_history[-1]) >= self._MAX_IDENTICAL_CONTINUE_THRESHOLD
        return (
            self._repeat_output_streak >= self._REPEAT_OUTPUT_THRESHOLD
            or self._no_progress_cycles >= self._NO_PROGRESS_THRESHOLD
            or self._saw_stall_signal
            or repeated_prompt
        )

    def _should_escalate_test_failures(self) -> bool:
        return self._test_failure_streak >= self._TEST_FAILURE_ESCALATION_THRESHOLD

    def _update_line_observations(self, line: str, stream_name: str) -> None:
        lowered = line.lower()
        normalized = re.sub(r"\s+", " ", lowered).strip()
        if normalized:
            if self._recent_output_lines and self._recent_output_lines[-1] == normalized:
                self._repeat_output_streak += 1
            else:
                self._repeat_output_streak = 0
            self._recent_output_lines.append(normalized)

        if any(token in lowered for token in _PARTIAL_OUTPUT_PATTERNS):
            self._saw_partial_since_continue = True
        if any(token in lowered for token in _STALL_PATTERNS):
            self._saw_stall_signal = True

        progress_tokens = ("completed", "done", "fixed", "resolved", "pass", "success")
        if any(token in lowered for token in progress_tokens):
            self._saw_progress_since_continue = True
            self._no_progress_cycles = 0
            self._saw_stall_signal = False

        current_failed = self._extract_failed_test_count(lowered)
        saw_test_failure = current_failed is not None or any(token in lowered for token in _TEST_FAILURE_PATTERNS)
        if saw_test_failure:
            self._track_test_failure_trend(current_failed)

        if stream_name == "stderr" and ("error" in lowered or "failed" in lowered):
            self._track_test_failure_trend(current_failed)

    def _extract_failed_test_count(self, lowered: str) -> int | None:
        patterns = (
            r"(\d+)\s+failed",
            r"failed:\s*(\d+)",
            r"failures?:\s*(\d+)",
        )
        for pattern in patterns:
            match = re.search(pattern, lowered)
            if match:
                return int(match.group(1))
        return None

    def _track_test_failure_trend(self, failed_count: int | None) -> None:
        if failed_count is None:
            self._test_failure_streak += 1
            return
        if self._best_failed_count is None or failed_count < self._best_failed_count:
            self._best_failed_count = failed_count
            self._test_failure_streak = 0
        elif self._last_failed_count is None or failed_count >= self._last_failed_count:
            self._test_failure_streak += 1
        else:
            self._test_failure_streak = max(0, self._test_failure_streak - 1)
        self._last_failed_count = failed_count

    def _handle_state_specific_actions(self, line: str) -> None:
        lowered = line.lower().strip()
        if self.status.state == RunState.DONE:
            self._last_action_summary = "state:done"
            if self._auto_continue_task and not self._auto_continue_task.done():
                self._auto_continue_task.cancel()
            self._schedule_completion_gate("done_output")
            return
        if self.status.state == RunState.BLOCKED:
            if self._is_hard_blocked_state():
                self._last_action_summary = "state:blocked_hard"
                return
            if lowered.endswith("?") or "need your input" in lowered or "missing" in lowered:
                self.status.summary = "Blocked: Codex requested input/context from operator."
            self._last_action_summary = "state:blocked_soft"
            if self.auto_continue:
                self._schedule_auto_continue("soft_blocked_output")
            return
        if self.status.state == RunState.INCOMPLETE and self.auto_continue:
            if not self._saw_progress_since_continue:
                self._no_progress_cycles += 1
            self._schedule_auto_continue("incomplete_output")

    def _write_journal_snapshot(self) -> None:
        failed_text = "n/a" if self._last_failed_count is None else str(self._last_failed_count)
        self._emit(
            AgentName.BROKER,
            "Journal snapshot: "
            f"iter={self.status.loop_count} "
            f"state={self.status.state.value} "
            f"action={self._last_action_summary} "
            f"escalation_hint={str(self._escalation_hint_used).lower()} "
            f"failed_tests={failed_text}",
        )

    async def _pump_stream(
        self,
        stream: asyncio.StreamReader | None,
        source: AgentName,
        stream_name: str,
    ) -> None:
        if stream is None:
            return
        while True:
            chunk = await stream.readline()
            if not chunk:
                break
            raw_line = chunk.decode("utf-8", errors="replace").strip()
            if not raw_line:
                continue
            line = strip_ansi(raw_line)
            if not line:
                continue
            lowered = line.lower()
            if "stdin is not a terminal" in lowered or "not a tty" in lowered:
                self.status.state = RunState.BLOCKED
                self.status.summary = (
                    "CLI requires a terminal (TTY). Current launch uses piped stdin/stdout. "
                    "Use a PTY/ConPTY runner for this agent."
                )
            self.status.state = derive_state_from_output(line, self.status.state)
            if self._maybe_apply_run_status(line):
                self.status.last_update_utc = _utc_now()
                self._emit(source, line, stream_name)
                continue
            if self._maybe_apply_completion_decision(line):
                self.status.last_update_utc = _utc_now()
                self._emit(source, line, stream_name)
                continue
            self._update_line_observations(line, stream_name)
            self._handle_state_specific_actions(line)
            if is_terminal_completion_signal(line):
                self._saw_terminal_completion_signal = True
            self.status.last_update_utc = _utc_now()
            self._emit(source, line, stream_name)

    async def _pump_pty_stream(self, source: AgentName, stream_name: str) -> None:
        if not self._pty_process:
            return
        while self._pty_process.isalive():
            try:
                data = await asyncio.to_thread(self._pty_process.readline)
            except Exception:
                break
            if not data:
                await asyncio.sleep(0.05)
                continue
            line = strip_ansi(data).strip()
            if not line:
                continue
            lowered = line.lower()
            if self._looks_like_pty_prompt_ready(line):
                self._pty_prompt_ready.set()
                await self._flush_initial_pty_task_if_ready()
            if (
                self._pty_task_injected
                and not self._pty_queue_commit_sent
                and "tab to queue message" in lowered
            ):
                self._pty_queue_commit_sent = True
                self._emit(AgentName.BROKER, "Queued prompt detected; sending commit submit.")
                await self._send_pty_submit("")
            if "stdin is not a terminal" in lowered or "not a tty" in lowered:
                self.status.state = RunState.BLOCKED
                self.status.summary = (
                    "CLI requires a terminal (TTY). Current launch still appears non-interactive. "
                    "Verify ConPTY environment for this shell."
                )
            if not self._pty_task_injected:
                self.status.last_update_utc = _utc_now()
                self._emit(source, line, stream_name)
                continue
            self.status.state = derive_state_from_output(line, self.status.state)
            if self._maybe_apply_run_status(line):
                self.status.last_update_utc = _utc_now()
                self._emit(source, line, stream_name)
                continue
            if self._maybe_apply_completion_decision(line):
                self.status.last_update_utc = _utc_now()
                self._emit(source, line, stream_name)
                continue
            self._update_line_observations(line, stream_name)
            self._handle_state_specific_actions(line)
            if is_terminal_completion_signal(line):
                self._saw_terminal_completion_signal = True
            self.status.last_update_utc = _utc_now()
            self._emit(source, line, stream_name)

    def _emit(self, source: AgentName, message: str, stream: str = "system") -> None:
        event = BrokerEvent(source=source, message=message, stream=stream)
        self._sink(event)
        self._append_log(event)
        if source == AgentName.CODEX:
            self._append_codex_journal(event)

    def _record_memory_run(self, summary: str, status: str) -> None:
        signature = (summary, status)
        if signature == self._last_memory_signature:
            return
        self._last_memory_signature = signature
        request = self._last_task_text.strip() or "broker_control"
        self._codex_mem.queue_add_run(request=request, summary=summary, status=status)

    def _append_log(self, event: BrokerEvent) -> None:
        line = f"{event.at.isoformat()} [{event.source.value}] [{event.stream}] {event.message}\n"
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(line)
        except Exception:
            return

    def _append_codex_journal(self, event: BrokerEvent) -> None:
        line = f"{event.at.isoformat()} [{event.stream}] {event.message}\n"
        try:
            self._codex_journal_path.parent.mkdir(parents=True, exist_ok=True)
            with self._codex_journal_path.open("a", encoding="utf-8") as fh:
                fh.write(line)
        except Exception:
            return

    def _is_hard_blocked_state(self) -> bool:
        if self.status.state != RunState.BLOCKED:
            return False
        summary = self.status.summary.lower()
        terminal_tokens = ("requires a terminal", "not a tty", "stdin is not a terminal", "conpty")
        return any(token in summary for token in terminal_tokens)
