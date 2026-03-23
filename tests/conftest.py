from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from cli_runner.broker.engine import BrokerEngine
from cli_runner.broker.models import BrokerEvent


@pytest.fixture
def event_queue() -> asyncio.Queue[BrokerEvent]:
    return asyncio.Queue()


@pytest.fixture
def sink(event_queue: asyncio.Queue[BrokerEvent]) -> Callable[[BrokerEvent], None]:
    def _sink(event: BrokerEvent) -> None:
        event_queue.put_nowait(event)

    return _sink


@pytest.fixture
async def engine(sink: Callable[[BrokerEvent], None]) -> BrokerEngine:
    broker = BrokerEngine(sink=sink)
    try:
        yield broker
    finally:
        await broker.shutdown()


async def wait_for_event(
    queue: asyncio.Queue[BrokerEvent],
    predicate: Callable[[BrokerEvent], bool],
    timeout: float = 3.0,
) -> BrokerEvent:
    async def _inner() -> BrokerEvent:
        while True:
            evt = await queue.get()
            if predicate(evt):
                return evt

    return await asyncio.wait_for(_inner(), timeout=timeout)

