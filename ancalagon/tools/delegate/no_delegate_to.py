# The delegate tool a session gets when it has no bus: same schema, nothing queued, nothing written.
from ancalagon.contracts.role import Role
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.delegate.delegate_args import DelegateArgs
from ancalagon.tools.delegate.delegating import (
    delegate_args,
    delegate_description,
    delegate_name,
)
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext


class NoDelegateTo(Tool[DelegateArgs]):
    cost = 1

    def __init__(self, role_name: str, role: Role):
        self.name = delegate_name(role_name)
        self.description = delegate_description(role_name, role)
        self.args_model = delegate_args(role_name, role)

    def run(self, args: DelegateArgs, ctx: ToolContext) -> ToolResult:
        return ctx.failure(self.name, f"cannot queue task {args.task_id}: this session has no bus")
