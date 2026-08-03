# Replaces an exact substring, refusing anything outside the workspace write root.
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.llm.schema_of import schema_of
from ancalagon.llm.tool_schema import ToolSchema
from ancalagon.tools.files.edit_args import EditArgs
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.workspace.scope_error import ScopeError


class EditFile:
    name = "edit_file"
    description = "Replace an exact substring in a file inside the workspace write root."

    def schema(self) -> ToolSchema:
        return schema_of(self.name, self.description, EditArgs)

    def run(self, arguments: str, ctx: ToolContext) -> ToolResult:
        args = EditArgs.model_validate_json(arguments)
        try:
            path = ctx.workspace.resolve_write(args.path)
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        original = path.read_text(encoding="utf-8")
        if args.old not in original:
            return ctx.failure(self.name, f"{args.old!r} not found in {path}")
        path.write_text(original.replace(args.old, args.new, 1), encoding="utf-8")
        return ctx.result(self.name, f"edited {path}")
