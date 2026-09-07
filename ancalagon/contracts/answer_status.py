# What an agent thinks of its own answer, which is not the same as how its run ended.
import enum


class AnswerStatus(enum.StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
