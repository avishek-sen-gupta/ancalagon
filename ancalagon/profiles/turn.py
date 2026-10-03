# The state one turn's decisions are allowed to read: the tools on offer, the budget left,
# the spend so far, and the children. Built fresh each pass of the loop and never kept.
import collections.abc
import dataclasses

import pydantic

from ancalagon.contracts.budget import Budget
from ancalagon.contracts.delivery import Delivery
from ancalagon.contracts.spend import Spend
from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.contracts.tool_spec import ToolSpec
from ancalagon.tools.registry.bound_tool import BoundTool
from ancalagon.tools.registry.no_tool import NO_TOOL, NoTool
from ancalagon.workspace.workspace import Workspace


@dataclasses.dataclass(frozen=True)
class Turn:
    spec: TaskSpec
    agent_id: int
    output_class: type[pydantic.BaseModel]
    offered: tuple[BoundTool, ...]
    remaining: Budget
    spent: Spend
    outstanding: tuple[int, ...]
    uncollected: tuple[int, ...]
    tries: int
    delivered: Delivery
    workspace: Workspace

    @property
    def final(self) -> bool:
        return self.remaining.turns_exhausted

    def bound(self, spec: ToolSpec, /) -> BoundTool | NoTool:
        held: collections.abc.Mapping[ToolSpec, BoundTool] = {t.spec: t for t in self.offered}
        return held.get(spec, NO_TOOL)
