# What edit_json does at the pointer it is given.
import enum


class JsonOp(enum.StrEnum):
    SET = "set"
    APPEND = "append"
    REMOVE = "remove"
