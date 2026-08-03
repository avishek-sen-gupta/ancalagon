# Stream-only transformation. Never -i, so it cannot mutate an artifact under analysis.
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.llm.schema_of import schema_of
from ancalagon.llm.tool_schema import ToolSchema
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.search.run_command import run_command
from ancalagon.tools.search.sed_args import SedArgs
from ancalagon.workspace.scope_error import ScopeError


class Sed:
    name = "sed"
    description = "Apply a sed script to a file and write the transformed stream to a new file."

    def schema(self) -> ToolSchema:
        return schema_of(self.name, self.description, SedArgs)

    def run(self, arguments: str, ctx: ToolContext) -> ToolResult:
        args = SedArgs.model_validate_json(arguments)
        try:
            path = ctx.workspace.resolve_read(args.path)
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        code, out, err = run_command(["sed", args.script, str(path)])
        if code != 0:
            return ctx.failure(self.name, err)
        return ctx.result(self.name, out)
