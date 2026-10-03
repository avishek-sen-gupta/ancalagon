# Queries a JSON or JSONL file with jq, so a large document need not be read whole.
import collections.abc

from ancalagon.contracts.tool_category import ToolCategory
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.artifacts.query_args import QueryArgs
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.search.run_command import run_command
from ancalagon.workspace.scope_error import ScopeError


def _option_fault(expression: str) -> str:
    if expression.startswith("-"):
        return f"filter may not begin with '-': {expression!r}"
    return ""


class QueryJson(Tool[QueryArgs]):
    name = "query_json"
    description = (
        "Run a jq filter over a JSON file and return only what matches, so a large "
        "document need not be read whole. Add --slurp semantics yourself if the file "
        "is JSONL. Example filters: '.nodes[].id', 'keys', '.[] | select(.kind)'."
    )
    category = ToolCategory.ARTIFACTS
    cost = 1
    args_model = QueryArgs

    def run(self, args: QueryArgs, ctx: ToolContext) -> ToolResult:
        if fault := _option_fault(args.filter):
            return ctx.failure(self, fault)
        try:
            path = ctx.workspace.resolve_read(args.path)
        except ScopeError as exc:
            return ctx.failure(self, str(exc))
        return self._queried(["jq", "-r", args.filter, str(path)], ctx)

    def _queried(self, command: collections.abc.Sequence[str], ctx: ToolContext) -> ToolResult:
        code, out, err = run_command(command)
        if code != 0:
            return ctx.failure(self, err)
        return ctx.result(self, out)
