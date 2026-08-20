# Shared test helpers for the unit suite.
from ancalagon.bus.bus import Bus
from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.contracts.event_source import EventSource


def settle(bus: Bus, agent: int, verdict: AgentStatus, pid: int = 1) -> None:
    bus.record(agent, AgentStatus.CLAIMED, EventSource.SUPERVISOR)
    bus.record(agent, AgentStatus.RUNNING, EventSource.SUPERVISOR, pid=pid)
    bus.record(agent, verdict, EventSource.SUPERVISOR)
