# Regex search. Compact path:line:text by default; structured=true for JSON records.
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.search.grep_args import GrepArgs
from ancalagon.tools.search.run_command import run_command
from ancalagon.workspace.scope_error import ScopeError


class Ripgrep(Tool):
    name = "ripgrep"
    description = (
        "Search files by regular expression. Returns path:line:text per match. "
        "Set structured=true for one JSON record per match instead."
    )
    cost = 1
    args_model = GrepArgs

    def run(self, arguments: str, ctx: ToolContext) -> ToolResult:
        args = GrepArgs.model_validate_json(arguments)
        try:
            roots = [str(ctx.workspace.resolve_read(r)) for r in args.roots]
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        flags = ["--json"] if args.structured else ["--line-number", "--no-heading"]
        flags.append("--no-require-git")
        code, out, err = run_command(["rg", *flags, "-e", args.pattern, "--", *roots])
        if code not in (0, 1):
            return ctx.failure(self.name, err)
        return ctx.result(self.name, out, ".jsonl" if args.structured else ".txt")
