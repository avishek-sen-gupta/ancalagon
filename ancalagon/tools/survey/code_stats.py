# Surveys a tree with scc: what languages, how much of each, where the complexity sits.
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.llm.schema_of import schema_of
from ancalagon.llm.tool_schema import ToolSchema
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.search.run_command import run_command
from ancalagon.tools.survey.stats_args import StatsArgs
from ancalagon.workspace.scope_error import ScopeError


class CodeStats(Tool):
    name = "code_stats"
    description = (
        "Survey a tree before reading it: languages, file and line counts, and an "
        "estimated complexity score. Set by_file=true to see which individual files "
        "carry the most complexity, which is usually where to start reading."
    )
    cost = 1

    def schema(self) -> ToolSchema:
        return schema_of(self.name, self.description, StatsArgs)

    def run(self, arguments: str, ctx: ToolContext) -> ToolResult:
        args = StatsArgs.model_validate_json(arguments)
        try:
            roots = [str(ctx.workspace.resolve_read(r)) for r in args.roots]
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        flags = ["--by-file"] if args.by_file else []
        code, out, err = run_command(["scc", "--no-cocomo", *flags, *roots])
        if code != 0:
            return ctx.failure(self.name, err)
        return ctx.result(self.name, out)
