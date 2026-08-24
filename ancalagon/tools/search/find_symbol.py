# Locates definitions with ctags over the files ripgrep would search, so both honour .gitignore.
import collections.abc

from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.search.run_command import run_command
from ancalagon.tools.search.searchable_files import searchable_files
from ancalagon.tools.search.symbol_args import SymbolArgs
from ancalagon.workspace.scope_error import ScopeError

# ctags does not read .gitignore, so vendored trees would swamp every result.
VENDOR = (
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "target",
    "build",
    "dist",
    "__pycache__",
    ".tox",
    "vendor",
    "site-packages",
    ".gradle",
    ".mvn",
)


def _named(tagged: str, name: str) -> str:
    if not name:
        return tagged
    wanted = name.lower()
    return "\n".join(
        line for line in tagged.splitlines() if line.split(" ", 1)[0].lower() == wanted
    )


class FindSymbol(Tool[SymbolArgs]):
    name = "find_symbol"
    description = (
        "Find where a symbol is defined, as name, kind, line, file and the declaring "
        "line itself. Unlike a text search this returns definitions rather than every "
        "mention. Omit name to list every definition in the given roots."
    )
    cost = 1
    args_model = SymbolArgs

    def run(self, args: SymbolArgs, ctx: ToolContext) -> ToolResult:
        try:
            roots = [str(ctx.workspace.resolve_read(r)) for r in args.roots]
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        return self._over(roots, args.name, ctx)

    def _over(
        self, roots: collections.abc.Sequence[str], name: str, ctx: ToolContext
    ) -> ToolResult:
        listed, files, err = searchable_files(roots, ())
        if listed not in (0, 1):
            return ctx.failure(self.name, err)
        if not files:
            return ctx.result(self.name, "")
        return self._tagged(files, name, ctx)

    def _tagged(
        self, files: collections.abc.Sequence[str], name: str, ctx: ToolContext
    ) -> ToolResult:
        code, tagged, failure = run_command(["ctags", "-x", "-L", "-"], stdin="\n".join(files))
        if code != 0:
            return ctx.failure(self.name, failure)
        return ctx.result(self.name, _named(tagged, name))
