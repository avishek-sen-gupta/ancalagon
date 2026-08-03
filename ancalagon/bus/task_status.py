# Lifecycle states a task row can hold; mirrored by a CHECK constraint in the schema.
import enum


class TaskStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    CRASHED = "crashed"
    TIMEOUT = "timeout"
    ABANDONED = "abandoned"
