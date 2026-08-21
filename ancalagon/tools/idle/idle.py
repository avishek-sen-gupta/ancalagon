# Stops an attempt to wait for a live child; there is nothing to wait for once none remain.
import pathlib

from ancalagon.bus.bus import Bus
from ancalagon.clock.clock import Clock
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

    def __init__(self, run_dir: pathlib.Path, agent: int, clock: Clock):
        self.run_dir = run_dir
        self.agent = agent
        self.clock = clock

    def run(self, args: IdleArgs, ctx: ToolContext) -> ToolResult:
        bus = Bus.open(self.run_dir / "bus.db", self.clock)
        snapshot = bus.snapshot()
        live = live_children(snapshot, self.agent)
        if not live:
            return ctx.failure(self.name, "nothing to wait for: no live children")
        payload = Idled(waiting_for=live)
        path = ctx.write_output(self.name, payload.text_for_model(), ".txt")
        return ToolResult(ok=True, summary=payload, path=path)
