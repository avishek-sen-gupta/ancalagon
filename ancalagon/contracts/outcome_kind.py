import enum


class OutcomeKind(enum.StrEnum):
    COMPLETED = "completed"
    EXHAUSTED = "exhausted"
    NEEDS_INPUT = "needs_input"
    FAILED = "failed"
    IDLING = "idling"
