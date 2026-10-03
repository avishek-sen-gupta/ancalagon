# Lists a directory, refusing anything outside the configured read roots.
from ancalagon.contracts.tool_category import ToolCategory
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.files.path_args import PathArgs
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.workspace.scope_error import ScopeError
from ancalagon.workspace.workspace import missing_hint


class ListDir(Tool[PathArgs]):
    name = "list_dir"
    description = "List a directory inside the configured read roots."
    category = ToolCategory.FILES
    cost = 1
    args_model = PathArgs

    def run(self, args: PathArgs, ctx: ToolContext) -> ToolResult:
        try:
            path = ctx.workspace.resolve_read(args.path)
        except ScopeError as exc:
            return ctx.failure(self, str(exc))
        if not ctx.workspace.is_dir(path):
            return ctx.failure(self, missing_hint(path))
        entries = "\n".join(sorted(p.name for p in ctx.workspace.iterdir(path)))
        return ctx.result(self, entries)
