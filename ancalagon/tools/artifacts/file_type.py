# Identifies what an artifact actually is, before anything tries to read it as text.
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.artifacts.path_arg import PathArg
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.search.run_command import run_command
from ancalagon.workspace.scope_error import ScopeError


class FileType(Tool[PathArg]):
    name = "file_type"
    description = (
        "Identify what a file is -- text, binary, archive, image, database -- before "
        "trying to read it. Use this first on anything whose format you do not know."
    )
    cost = 1
    args_model = PathArg

    def run(self, args: PathArg, ctx: ToolContext) -> ToolResult:
        try:
            path = ctx.workspace.resolve_read(args.path)
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        code, out, err = run_command(["file", "-b", str(path)])
        if code != 0:
            return ctx.failure(self.name, err)
        return ctx.result(self.name, out)
