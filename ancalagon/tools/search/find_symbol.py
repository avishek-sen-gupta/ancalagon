# Locates definitions with ctags: where a symbol is declared, not merely mentioned.
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.llm.schema_of import schema_of
from ancalagon.llm.tool_schema import ToolSchema
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.search.run_command import run_command
from ancalagon.tools.search.symbol_args import SymbolArgs
from ancalagon.workspace.scope_error import ScopeError


class FindSymbol:
    name = "find_symbol"
    description = (
        "Find where a symbol is defined, as name, kind, line, file and the declaring "
        "line itself. Unlike a text search this returns definitions rather than every "
        "mention. Omit name to list every definition in the given roots."
    )
    cost = 1

    def schema(self) -> ToolSchema:
        return schema_of(self.name, self.description, SymbolArgs)

    def run(self, arguments: str, ctx: ToolContext) -> ToolResult:
        args = SymbolArgs.model_validate_json(arguments)
        try:
            roots = [str(ctx.workspace.resolve_read(r)) for r in args.roots]
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        code, out, err = run_command(["ctags", "-x", "-R", *roots])
        if code != 0:
            return ctx.failure(self.name, err)
        if args.name:
            wanted = args.name.lower()
            out = "\n".join(
                line for line in out.splitlines() if line.split(" ", 1)[0].lower() == wanted
            )
        return ctx.result(self.name, out)
