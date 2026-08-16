# The sandboxes a run may choose between, named in the config.
import enum


class Strategy(enum.StrEnum):
    NONE = "none"
    FENCE = "fence"
