# Writes a file, refusing anything outside the workspace write root.
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.files.write_args import WriteArgs
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.workspace.scope_error import ScopeError


class WriteFile(Tool[WriteArgs]):
    name = "write_file"
    description = "Write a file inside the workspace write root."
    cost = 1
    args_model = WriteArgs

    def run(self, args: WriteArgs, ctx: ToolContext) -> ToolResult:
        try:
            path = ctx.workspace.resolve_write(args.path)
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args.content, encoding="utf-8")
        return ctx.result(self.name, f"wrote {len(args.content)} chars to {path}")
