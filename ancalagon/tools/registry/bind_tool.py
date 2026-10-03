# The one place a tool call's JSON text becomes the model that tool declared, and is reviewed.
import pydantic

from ancalagon.contracts.accepted import Accepted
from ancalagon.contracts.any_tool import AnyTool
from ancalagon.contracts.refused import Refused
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.contracts.tool_spec import ToolSpec
from ancalagon.llm.schema_of import schema_of
from ancalagon.tools.registry.after import After
from ancalagon.tools.registry.before import Before
from ancalagon.tools.registry.bound_tool import BoundTool
from ancalagon.tools.registry.composite_after import CompositeAfter
from ancalagon.tools.registry.composite_before import CompositeBefore
from ancalagon.tools.registry.tool import ArgsT, Tool
from ancalagon.tools.registry.tool_context import ToolContext

NO_BEFORE = CompositeBefore(())
NO_AFTER = CompositeAfter(())


def _wrong(tool: AnyTool, hook: str, got: pydantic.BaseModel, wanted: str) -> str:
    return f"{tool.name}'s {hook} hook returned {type(got).__name__}, not {wanted}"


def _faults(tool: AnyTool, exc: pydantic.ValidationError) -> str:
    listed = "\n".join(
        f"  {'.'.join(str(part) for part in problem['loc'])}: {problem['msg']}"
        for problem in exc.errors(include_input=False)
    )
    return f"{tool.name} arguments are invalid:\n{listed}"


def _as_result(tool: AnyTool, given: pydantic.BaseModel, ctx: ToolContext) -> ToolResult:
    if not isinstance(given, ToolResult):
        return ctx.failure(tool, _wrong(tool, "after", given, "ToolResult"))
    return given


def _reviewed(
    tool: Tool[ArgsT], after: After, args: ArgsT, ran: ToolResult, ctx: ToolContext
) -> ToolResult:
    match after(args, ran, ctx):
        case Refused(reason=reason):
            return ctx.failure(tool, reason)
        case Accepted(value=accepted):
            return _as_result(tool, accepted, ctx)


def _ran(
    tool: Tool[ArgsT], after: After, given: pydantic.BaseModel, ctx: ToolContext
) -> ToolResult:
    if not isinstance(given, tool.args_model):
        wanted = tool.args_model.__name__
        return ctx.failure(tool, _wrong(tool, "before", given, wanted))
    return _reviewed(tool, after, given, tool.run(given, ctx), ctx)


def _gated(
    tool: Tool[ArgsT], before: Before, after: After, args: ArgsT, ctx: ToolContext
) -> ToolResult:
    match before(args, ctx):
        case Refused(reason=reason):
            return ctx.failure(tool, reason)
        case Accepted(value=accepted):
            return _ran(tool, after, accepted, ctx)


def _invoked(
    tool: Tool[ArgsT], before: Before, after: After, arguments: str, ctx: ToolContext
) -> ToolResult:
    try:
        args = tool.args_model.model_validate_json(arguments)
    except pydantic.ValidationError as exc:
        return ctx.failure(tool, _faults(tool, exc))
    return _gated(tool, before, after, args, ctx)


def bind_tool(tool: Tool[ArgsT], before: Before = NO_BEFORE, after: After = NO_AFTER) -> BoundTool:
    return BoundTool(
        spec=ToolSpec(
            source=type(tool),
            category=tool.category,
            cost=tool.cost,
            declaration=schema_of(tool.name, tool.description, tool.args_model),
        ),
        invoke=lambda arguments, ctx: _invoked(tool, before, after, arguments, ctx),
    )
