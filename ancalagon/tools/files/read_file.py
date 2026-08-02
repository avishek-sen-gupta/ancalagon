from ancalagon.contracts.tool_result import ToolResult
from ancalagon.llm.schema_of import schema_of
from ancalagon.llm.tool_schema import ToolSchema
from ancalagon.tools.files.path_args import PathArgs
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.workspace.scope_error import ScopeError


class ReadFile:
    name = "read_file"
    description = "Read a file inside the configured read roots."

    def schema(self) -> ToolSchema:
        return schema_of(self.name, self.description, PathArgs)

    def run(self, arguments: str, ctx: ToolContext) -> ToolResult:
        args = PathArgs.model_validate_json(arguments)
        try:
            path = ctx.workspace.resolve_read(args.path)
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        return ctx.result(self.name, path.read_text(encoding="utf-8"))
