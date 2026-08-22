import enum


class NodeKind(enum.StrEnum):
    TASK = "task"
    AGENT = "agent"
    TOOL_CALL = "tool_call"
