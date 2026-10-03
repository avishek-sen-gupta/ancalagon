import enum


class EdgeKind(enum.Enum):
    SPAWNED = "spawned"
    WOKE = "woke"
    CALLED = "called"
    DELEGATED = "delegated"
    COLLECTED = "collected"
