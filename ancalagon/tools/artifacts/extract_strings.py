# Pulls printable runs out of a binary: the fastest way to guess what one does.
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.llm.schema_of import schema_of
from ancalagon.llm.tool_schema import ToolSchema
from ancalagon.tools.artifacts.strings_args import StringsArgs
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.search.run_command import run_command
from ancalagon.workspace.scope_error import ScopeError


class ExtractStrings(Tool):
    name = "extract_strings"
    description = (
        "Pull printable text out of a binary or other non-text artifact. Raise "
        "min_length to cut noise; embedded paths, messages and format strings often "
        "reveal what the thing does."
    )
    cost = 1

    def schema(self) -> ToolSchema:
        return schema_of(self.name, self.description, StringsArgs)

    def run(self, arguments: str, ctx: ToolContext) -> ToolResult:
        args = StringsArgs.model_validate_json(arguments)
        try:
            path = ctx.workspace.resolve_read(args.path)
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        code, out, err = run_command(["strings", "-n", str(args.min_length), str(path)])
        if code != 0:
            return ctx.failure(self.name, err)
        return ctx.result(self.name, out)
