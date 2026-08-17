# Structural search by AST pattern, over the files ripgrep would search.
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.search.grep_args import GrepArgs
from ancalagon.tools.search.run_command import run_command
from ancalagon.tools.search.searchable_files import fits_in_arguments, searchable_files
from ancalagon.workspace.scope_error import ScopeError


class AstGrep(Tool[GrepArgs]):
    name = "ast_grep"
    description = "Structural code search by AST pattern."
    cost = 1
    args_model = GrepArgs

    def run(self, args: GrepArgs, ctx: ToolContext) -> ToolResult:
        try:
            roots = [str(ctx.workspace.resolve_read(r)) for r in args.roots]
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        listed, files, err = searchable_files(roots)
        if listed not in (0, 1):
            return ctx.failure(self.name, err)
        if not files:
            return ctx.result(self.name, "")
        targets = files if fits_in_arguments(files) else roots
        code, found, failure = run_command(["ast-grep", "run", "--pattern", args.pattern, *targets])
        if code not in (0, 1):
            return ctx.failure(self.name, failure)
        return ctx.result(self.name, found)
