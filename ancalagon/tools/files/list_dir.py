# Lists a directory, refusing anything outside the configured read roots.
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.llm.schema_of import schema_of
from ancalagon.llm.tool_schema import ToolSchema
from ancalagon.tools.files.path_args import PathArgs
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.workspace.scope_error import ScopeError
from ancalagon.workspace.workspace import missing_hint


class ListDir(Tool):
    name = "list_dir"
    description = "List a directory inside the configured read roots."
    cost = 1

    def schema(self) -> ToolSchema:
        return schema_of(self.name, self.description, PathArgs)

    def run(self, arguments: str, ctx: ToolContext) -> ToolResult:
        args = PathArgs.model_validate_json(arguments)
        try:
            path = ctx.workspace.resolve_read(args.path)
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        if not path.is_dir():
            return ctx.failure(self.name, missing_hint(path))
        entries = "\n".join(sorted(p.name for p in path.iterdir()))
        return ctx.result(self.name, entries)
