# Stops an attempt until something arrives for it: a child finishing, or whatever an agent
# that never answers is standing by for.
from ancalagon.bus.bus import Bus
from ancalagon.contracts.idled import Idled
from ancalagon.contracts.tool_category import ToolCategory
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.schedule.live_children import live_children
from ancalagon.tools.idle.idle_args import IdleArgs
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext


class Idle(Tool[IdleArgs]):
    name = "idle"
    description = (
        "Stop and wait. Use when you have nothing left to do: your children are still working "
        "and you need one of them to report back, or there is nothing for you until something "
        "arrives. This does not consume your tool-call budget."
    )
    category = ToolCategory.LIFECYCLE
    cost = 0
    args_model = IdleArgs

    def __init__(self, bus: Bus, agent: int):
        self.bus = bus
        self.agent = agent

    def run(self, args: IdleArgs, ctx: ToolContext) -> ToolResult:
        snapshot = self.bus.snapshot()
        seen = max((e.id for events in snapshot.events.values() for e in events), default=0)
        payload = Idled(waiting_for=live_children(snapshot, self.agent), seen_through=seen)
        path = ctx.write_output(self.name, payload.text_for_model(), ".txt")
        return ToolResult(ok=True, summary=payload, path=path)
