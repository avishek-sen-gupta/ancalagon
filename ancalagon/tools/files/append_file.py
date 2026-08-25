# Adds a line to the end of a file without reading it, so a concurrent writer is not lost.
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.files.append_args import AppendArgs
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.workspace.scope_error import ScopeError


class AppendFile(Tool[AppendArgs]):
    name = "append_file"
    description = (
        "Add one line to the end of a file inside the workspace write root, creating it if "
        "it is not there. Use this rather than write_file to add to a file others also "
        "write to: it never reads the file, so it cannot overwrite what arrived since you "
        "last read."
    )
    cost = 1
    args_model = AppendArgs

    def run(self, args: AppendArgs, ctx: ToolContext) -> ToolResult:
        try:
            ctx.workspace.append_line(args.path, args.content)
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        return ctx.result(self.name, f"appended {len(args.content)} chars to {args.path}")
