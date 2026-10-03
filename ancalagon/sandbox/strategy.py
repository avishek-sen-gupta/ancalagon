# The sandboxes a run may choose between, named in the config.
import enum


class Strategy(enum.Enum):
    NONE = "none"
    FENCE = "fence"
