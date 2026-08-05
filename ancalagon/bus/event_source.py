# Which party observed an event, so the log explains itself.
import enum


class EventSource(enum.StrEnum):
    SUPERVISOR = "supervisor"
    WORKER = "worker"
