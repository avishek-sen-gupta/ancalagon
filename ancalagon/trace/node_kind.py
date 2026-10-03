import enum


class NodeKind(enum.Enum):
    TASK = "task"
    AGENT = "agent"
    TOOL_CALL = "tool_call"
