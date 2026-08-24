# The one place a tool call's JSON text becomes the model that tool declared, and is reviewed.
import pydantic

from ancalagon.contracts.accepted import Accepted
from ancalagon.contracts.refused import Refused
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.llm.schema_of import schema_of
from ancalagon.tools.registry.after import After
from ancalagon.tools.registry.before import Before
from ancalagon.tools.registry.bound_tool import BoundTool
from ancalagon.tools.registry.tool import ArgsT, Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.registry.unchecked_after import unchecked_after
from ancalagon.tools.registry.unchecked_before import unchecked_before


def _wrong(name: str, hook: str, got: pydantic.BaseModel, wanted: str) -> str:
    return f"{name}'s {hook} hook returned {type(got).__name__}, not {wanted}"


def _as_result(name: str, given: pydantic.BaseModel, ctx: ToolContext) -> ToolResult:
    if not isinstance(given, ToolResult):
        return ctx.failure(name, _wrong(name, "after", given, "ToolResult"))
    return given


def _reviewed(
    tool: Tool[ArgsT], after: After, args: ArgsT, ran: ToolResult, ctx: ToolContext
) -> ToolResult:
    match after(args, ran, ctx):
        case Refused(reason=reason):
            return ctx.failure(tool.name, reason)
        case Accepted(value=accepted):
            return _as_result(tool.name, accepted, ctx)


def _ran(
    tool: Tool[ArgsT], after: After, given: pydantic.BaseModel, ctx: ToolContext
) -> ToolResult:
    if not isinstance(given, tool.args_model):
        wanted = tool.args_model.__name__
        return ctx.failure(tool.name, _wrong(tool.name, "before", given, wanted))
    return _reviewed(tool, after, given, tool.run(given, ctx), ctx)


def _invoked(
    tool: Tool[ArgsT], before: Before, after: After, arguments: str, ctx: ToolContext
) -> ToolResult:
    args = tool.args_model.model_validate_json(arguments)
    match before(args, ctx):
        case Refused(reason=reason):
            return ctx.failure(tool.name, reason)
        case Accepted(value=accepted):
            return _ran(tool, after, accepted, ctx)


def bind_tool(
    tool: Tool[ArgsT], before: Before = unchecked_before, after: After = unchecked_after
) -> BoundTool:
    return BoundTool(
        name=tool.name,
        cost=tool.cost,
        declaration=schema_of(tool.name, tool.description, tool.args_model),
        invoke=lambda arguments, ctx: _invoked(tool, before, after, arguments, ctx),
    )
