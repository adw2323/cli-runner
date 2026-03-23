from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class AgentName(str, Enum):
    CODEX = "codex"
    BROKER = "broker"


class RunState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    BLOCKED = "blocked"
    INCOMPLETE = "incomplete"
    DONE = "done"
    FAILED = "failed"
    STOPPED = "stopped"


class TaskMode(str, Enum):
    CODEX_ONLY = "codex_only"


@dataclass(slots=True)
class BrokerEvent:
    source: AgentName
    message: str
    stream: str = "system"
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class BrokerStatus:
    state: RunState = RunState.IDLE
    active_agent: AgentName = AgentName.BROKER
    loop_count: int = 0
    mode: TaskMode = TaskMode.CODEX_ONLY
    summary: str = "idle"
    last_update_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
