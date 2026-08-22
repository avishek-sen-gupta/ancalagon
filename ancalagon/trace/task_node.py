import typing

import pydantic

from ancalagon.trace.node_kind import NodeKind


class TaskNode(pydantic.BaseModel, frozen=True):
    kind: typing.Literal[NodeKind.TASK] = NodeKind.TASK
    id: int
    dir: str
    parent_agent: int
