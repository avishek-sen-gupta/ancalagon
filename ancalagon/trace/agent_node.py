import typing

import pydantic

from ancalagon.contracts.agent_status import AgentStatus
from ancalagon.trace.node_kind import NodeKind


class AgentNode(pydantic.BaseModel, frozen=True):
    kind: typing.Literal["agent"] = NodeKind.AGENT.value
    id: int
    task: int
    last_status: AgentStatus
    started: str
    ended: str
