# Replaces an exact substring, refusing anything outside the workspace write root.
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.files.edit_args import EditArgs
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.workspace.scope_error import ScopeError


class EditFile(Tool[EditArgs]):
    name = "edit_file"
    description = "Replace an exact substring in a file inside the workspace write root."
    cost = 1
    args_model = EditArgs

    def run(self, args: EditArgs, ctx: ToolContext) -> ToolResult:
        try:
            path = ctx.workspace.resolve_write(args.path)
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        original = ctx.workspace.read_text(path)
        if args.old not in original:
            return ctx.failure(self.name, f"{args.old!r} not found in {path}")
        ctx.workspace.write_text(path, original.replace(args.old, args.new, 1))
        return ctx.result(self.name, f"edited {path}")
