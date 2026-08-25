# A reshaped view of a file, for reading. The original is never touched: sed without -i.
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.search.run_command import run_command
from ancalagon.tools.search.transform_args import TransformArgs
from ancalagon.workspace.scope_error import ScopeError


class TransformFile(Tool[TransformArgs]):
    name = "transform_file"
    description = (
        "Read a file through a transformation, when the file as it stands is hard to read. "
        "Strip comments, drop blank lines, or keep only the region you care about, and get "
        "the result back as a new file you can read. The original is never changed, so this "
        "cannot edit anything -- use edit_file or append_file for that."
    )
    cost = 1
    args_model = TransformArgs

    def run(self, args: TransformArgs, ctx: ToolContext) -> ToolResult:
        try:
            path = ctx.workspace.resolve_read(args.path)
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        code, out, err = run_command(["sed", "-e", args.script, "--", str(path)])
        if code != 0:
            return ctx.failure(self.name, err)
        return ctx.result(self.name, out)
