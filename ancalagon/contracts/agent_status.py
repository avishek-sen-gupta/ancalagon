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
    EXITED = "exited"
    IDLING = "idling"
    COLLECTED = "collected"
