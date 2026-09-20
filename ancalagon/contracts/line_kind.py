# Which kind of line a log event carries, so the union discriminates on one field.
import enum


class LineKind(enum.StrEnum):
    MESSAGE = "message"
    LIFECYCLE = "lifecycle"
