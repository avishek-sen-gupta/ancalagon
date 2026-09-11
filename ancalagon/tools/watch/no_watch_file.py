# The watch tool a session gets when it has no bus: same schema, nothing queued, nothing written.
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.watch.watch_args import WatchArgs
from ancalagon.tools.watch.watch_file import WatchFile


class NoWatchFile(Tool[WatchArgs]):
    name = WatchFile.name
    description = WatchFile.description
    cost = WatchFile.cost
    args_model = WatchFile.args_model

    def run(self, args: WatchArgs, ctx: ToolContext) -> ToolResult:
        return ctx.failure(self.name, f"cannot watch {args.path}: this session has no bus")
