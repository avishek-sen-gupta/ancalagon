# Queries a JSON or JSONL file with jq, so a large document need not be read whole.
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.artifacts.query_args import QueryArgs
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.search.run_command import run_command
from ancalagon.workspace.scope_error import ScopeError


class QueryJson(Tool[QueryArgs]):
    name = "query_json"
    description = (
        "Run a jq filter over a JSON file and return only what matches, so a large "
        "document need not be read whole. Add --slurp semantics yourself if the file "
        "is JSONL. Example filters: '.nodes[].id', 'keys', '.[] | select(.kind)'."
    )
    cost = 1
    args_model = QueryArgs

    def run(self, args: QueryArgs, ctx: ToolContext) -> ToolResult:
        if args.filter.startswith("-"):
            return ctx.failure(self.name, f"filter may not begin with '-': {args.filter!r}")
        try:
            path = ctx.workspace.resolve_read(args.path)
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        code, out, err = run_command(["jq", "-r", args.filter, str(path)])
        if code != 0:
            return ctx.failure(self.name, err)
        return ctx.result(self.name, out)
