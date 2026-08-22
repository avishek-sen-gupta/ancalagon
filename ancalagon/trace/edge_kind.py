import enum


class EdgeKind(enum.StrEnum):
    SPAWNED = "spawned"
    WOKE = "woke"
    CALLED = "called"
    DELEGATED = "delegated"
    COLLECTED = "collected"
