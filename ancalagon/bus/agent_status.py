# The states an agent can be observed in; mirrored by a CHECK constraint in the schema.
import enum


class AgentStatus(enum.StrEnum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    COMPLETED = "completed"
    NEEDS_INPUT = "needs_input"
    EXHAUSTED = "exhausted"
    FAILED = "failed"
    CRASHED = "crashed"
    TIMED_OUT = "timed_out"
    ABANDONED = "abandoned"
    EXITED = "exited"


TERMINAL = frozenset(
    {
        AgentStatus.COMPLETED,
        AgentStatus.NEEDS_INPUT,
        AgentStatus.EXHAUSTED,
        AgentStatus.FAILED,
        AgentStatus.CRASHED,
        AgentStatus.TIMED_OUT,
        AgentStatus.ABANDONED,
        AgentStatus.EXITED,
    }
)
