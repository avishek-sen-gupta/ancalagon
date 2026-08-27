# Shared test helpers for the unit suite.
import collections.abc
import pathlib
import sys

import pytest

from ancalagon.bus.lifecycle_store import LifecycleStore
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.event_source import EventSource


def settle(
    bus: LifecycleStore, agent: int, verdict: AgentStatus, pid: int = 1, summary: str = ""
) -> None:
    bus.record(agent, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
    bus.record(agent, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=pid)
    bus.record(agent, verdict, EventSource.SUPERVISOR, summary=summary)


@pytest.fixture
def importable() -> collections.abc.Iterator[collections.abc.Callable[[pathlib.Path], None]]:
    path_before = list(sys.path)
    modules_before = set(sys.modules)
    yield lambda directory: sys.path.insert(0, str(directory))
    sys.path[:] = path_before
    for name in set(sys.modules) - modules_before:
        del sys.modules[name]
