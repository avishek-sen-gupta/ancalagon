import typing

import pydantic

from ancalagon.trace.node_kind import NodeKind


class ToolCallNode(pydantic.BaseModel, frozen=True):
    kind: typing.Literal[NodeKind.TOOL_CALL] = NodeKind.TOOL_CALL
    id: int
    agent: int
    name: str
    ts: str
    ok: bool
    path: str
