import typing

import pydantic

from ancalagon.trace.node_kind import NodeKind


class ToolCallNode(pydantic.BaseModel, frozen=True):
    kind: typing.Literal["tool_call"] = NodeKind.TOOL_CALL.value
    id: int
    agent: int
    name: str
    ts: str
    ok: bool
    path: str
