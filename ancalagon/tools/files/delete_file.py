# Deletes a file, refusing anything outside the workspace write root.
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.llm.schema_of import schema_of
from ancalagon.llm.tool_schema import ToolSchema
from ancalagon.tools.files.path_args import PathArgs
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.workspace.scope_error import ScopeError


class DeleteFile:
    name = "delete_file"
    description = "Delete a file inside the workspace write root."

    def schema(self) -> ToolSchema:
        return schema_of(self.name, self.description, PathArgs)

    def run(self, arguments: str, ctx: ToolContext) -> ToolResult:
        args = PathArgs.model_validate_json(arguments)
        try:
            path = ctx.workspace.resolve_write(args.path)
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        path.unlink()
        return ctx.result(self.name, f"deleted {path}")
