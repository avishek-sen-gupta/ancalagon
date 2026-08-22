# The nodes a renderer looks up by id while drawing edges.
import collections.abc

import pydantic

from ancalagon.trace.agent_node import AgentNode
from ancalagon.trace.tool_call_node import ToolCallNode


class Lanes(pydantic.BaseModel, frozen=True):
    agents: collections.abc.Mapping[int, AgentNode]
    calls: collections.abc.Mapping[int, ToolCallNode]
