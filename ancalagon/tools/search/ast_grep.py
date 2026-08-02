from ancalagon.contracts.tool_result import ToolResult
from ancalagon.llm.schema_of import schema_of
from ancalagon.llm.tool_schema import ToolSchema
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.search.grep_args import GrepArgs
from ancalagon.tools.search.run_command import run_command
from ancalagon.workspace.scope_error import ScopeError


class AstGrep:
    name = "ast_grep"
    description = "Structural code search by AST pattern."

    def schema(self) -> ToolSchema:
        return schema_of(self.name, self.description, GrepArgs)

    def run(self, arguments: str, ctx: ToolContext) -> ToolResult:
        args = GrepArgs.model_validate_json(arguments)
        try:
            roots = [str(ctx.workspace.resolve_read(r)) for r in args.roots]
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        code, out, err = run_command(["ast-grep", "run", "--pattern", args.pattern, *roots])
        if code not in (0, 1):
            return ctx.failure(self.name, err)
        return ctx.result(self.name, out)
