# Stream-only transformation. Never -i, so it cannot mutate an artifact under analysis.
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.search.run_command import run_command
from ancalagon.tools.search.sed_args import SedArgs
from ancalagon.workspace.scope_error import ScopeError


class Sed(Tool[SedArgs]):
    name = "sed"
    description = "Apply a sed script to a file and write the transformed stream to a new file."
    cost = 1
    args_model = SedArgs

    def run(self, args: SedArgs, ctx: ToolContext) -> ToolResult:
        try:
            path = ctx.workspace.resolve_read(args.path)
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        code, out, err = run_command(["sed", "-e", args.script, "--", str(path)])
        if code != 0:
            return ctx.failure(self.name, err)
        return ctx.result(self.name, out)
