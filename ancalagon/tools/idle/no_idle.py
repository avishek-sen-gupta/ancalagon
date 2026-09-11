# The idle tool a session gets when it has no bus: same schema, refuses instead of indexing an empty snapshot.
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.idle.idle import Idle
from ancalagon.tools.idle.idle_args import IdleArgs
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext


class NoIdle(Tool[IdleArgs]):
    name = Idle.name
    description = Idle.description
    cost = Idle.cost
    args_model = Idle.args_model

    def run(self, args: IdleArgs, ctx: ToolContext) -> ToolResult:
        return ctx.failure(self.name, "nothing to wait for: this session has no bus")
