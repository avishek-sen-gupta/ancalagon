# Stops an attempt to wait for a live child; there is nothing to wait for once none remain.
from ancalagon.bus.bus import Bus
from ancalagon.contracts.idled import Idled
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.schedule.live_children import live_children
from ancalagon.tools.idle.idle_args import IdleArgs
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext


class Idle(Tool[IdleArgs]):
    name = "idle"
    description = (
        "Stop and wait for a delegated child to finish. Use when your children are still "
        "working and you have nothing left to do until one of them reports back. This does "
        "not consume your tool-call budget."
    )
    cost = 0
    args_model = IdleArgs

    def __init__(self, bus: Bus, agent: int):
        self.bus = bus
        self.agent = agent

    def run(self, args: IdleArgs, ctx: ToolContext) -> ToolResult:
        snapshot = self.bus.snapshot()
        live = live_children(snapshot, self.agent)
        if not live:
            return ctx.failure(self.name, "nothing to wait for: no live children")
        seen = max((e.id for events in snapshot.events.values() for e in events), default=0)
        payload = Idled(waiting_for=live, seen_through=seen)
        path = ctx.write_output(self.name, payload.text_for_model(), ".txt")
        return ToolResult(ok=True, summary=payload, path=path)
