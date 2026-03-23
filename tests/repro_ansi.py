from __future__ import annotations
import asyncio
from unittest.mock import MagicMock
from cli_orchestrator_ui.broker.engine import BrokerEngine
from cli_orchestrator_ui.broker.models import AgentName, BrokerEvent

def test_ansi_leaking():
    events = []
    def sink(event):
        events.append(event)
    
    broker = BrokerEngine(sink=sink)
    # Simulate ANSI sequences from PTY
    ansi_msg = "\x1b[31mRed Text\x1b[0m \x1b[2J\x1b[H"
    broker._emit(AgentName.CODEX, ansi_msg, "pty")
    
    assert len(events) == 1
    assert events[0].message == ansi_msg
    # If this is what's being sent to the UI, it's raw ANSI.
