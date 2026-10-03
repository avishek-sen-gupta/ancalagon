# The read-only git operations an agent may run.
import enum


class GitOperation(enum.Enum):
    LOG = "log"
    BLAME = "blame"
    SHOW = "show"
