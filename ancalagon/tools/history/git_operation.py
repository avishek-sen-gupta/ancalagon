# The read-only git operations an agent may run.
import enum


class GitOperation(enum.StrEnum):
    LOG = "log"
    BLAME = "blame"
    SHOW = "show"
