import enum


class OutcomeKind(enum.StrEnum):
    COMPLETED = "completed"
    EXHAUSTED = "exhausted"
    NEEDS_INPUT = "needs_input"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
