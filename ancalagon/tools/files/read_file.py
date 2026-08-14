# Reads a file, refusing anything outside the configured read roots.
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.files.read_args import ReadArgs
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.workspace.scope_error import ScopeError
from ancalagon.workspace.workspace import missing_hint


class ReadFile(Tool[ReadArgs]):
    name = "read_file"
    description = (
        "Read a file inside the configured read roots. Returns whole lines from offset, "
        "and states which lines it showed of how many exist. If the file is larger than "
        "one reply can carry, call again with offset set past the last line shown."
    )
    cost = 1
    args_model = ReadArgs

    def run(self, args: ReadArgs, ctx: ToolContext) -> ToolResult:
        try:
            path = ctx.workspace.resolve_read(args.path)
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        if not path.is_file():
            return ctx.failure(self.name, missing_hint(path))
        lines = path.read_text(encoding="utf-8").splitlines()
        end = len(lines) if args.limit <= 0 else min(len(lines), args.offset + args.limit)
        shown = lines[args.offset : end]
        return ctx.paged(self.name, shown, args.offset, len(lines))
