# What edit_json does at the pointer it is given.
import enum


class JsonOp(enum.Enum):
    SET = "set"
    APPEND = "append"
    REMOVE = "remove"
