# The one place a tool call's JSON text becomes the model that tool declared.
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.registry.bound_tool import BoundTool
from ancalagon.tools.registry.tool import ArgsT, Tool
from ancalagon.tools.registry.tool_context import ToolContext


def bind_tool(tool: Tool[ArgsT]) -> BoundTool:
    def invoke(arguments: str, ctx: ToolContext) -> ToolResult:
        return tool.run(tool.args_model.model_validate_json(arguments), ctx)

    return BoundTool(
        name=tool.name,
        description=tool.description,
        cost=tool.cost,
        args_model=tool.args_model,
        invoke=invoke,
    )
