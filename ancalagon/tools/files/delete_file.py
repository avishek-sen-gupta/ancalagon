# Deletes a file, refusing anything outside a write root.
from ancalagon.contracts.tool_category import ToolCategory
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.files.path_args import PathArgs
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.workspace.scope_error import ScopeError


class DeleteFile(Tool[PathArgs]):
    name = "delete_file"
    description = "Delete a file inside a write root."
    category = ToolCategory.FILES
    cost = 1
    args_model = PathArgs

    def run(self, args: PathArgs, ctx: ToolContext) -> ToolResult:
        try:
            path = ctx.workspace.resolve_write(args.path)
        except ScopeError as exc:
            return ctx.failure(self, str(exc))
        ctx.workspace.unlink(path)
        return ctx.result(self, f"deleted {path}")
