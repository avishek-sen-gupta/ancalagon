import enum


class OutcomeKind(enum.Enum):
    COMPLETED = "completed"
    EXHAUSTED = "exhausted"
    NEEDS_INPUT = "needs_input"
    FAILED = "failed"
    IDLING = "idling"
