# Queues one task for one role; the supervisor spawns it.
import pathlib

import pydantic

from ancalagon.bus.bus import Bus
from ancalagon.clock.clock import Clock
from ancalagon.contracts.agent_spec import AgentSpec
from ancalagon.contracts.resolve import resolve_class
from ancalagon.contracts.role import Role
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.tools.delegate.delegate_args import DelegateArgs
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext


class DelegateTo(Tool[DelegateArgs]):
    cost = 1

    def __init__(
        self, role_name: str, role: Role, run_dir: pathlib.Path, parent: int, clock: Clock
    ):
        self.name = f"delegate_{role_name}"
        self.description = (
            f"Queue a {role_name} task. Returns its task id immediately without waiting. "
            f"That agent is told: {role.behaviour}"
        )
        self.role = role
        self.run_dir = run_dir
        self.parent = parent
        self.clock = clock
        self.args_model = pydantic.create_model(
            f"DelegateTo{role_name.title().replace('_', '')}Args",
            __base__=DelegateArgs,
            input=(resolve_class(role.input), ...),
        )

    def run(self, args: DelegateArgs, ctx: ToolContext) -> ToolResult:
        task_dir = self.run_dir / "tasks" / args.task_id
        bus = Bus.open(self.run_dir / "bus.db", self.clock)
        active = bus.active_for(task_dir)
        if active:
            return ctx.failure(
                self.name,
                f"task {args.task_id} is already {active[0].status.value} as agent {active[0].agent}",
            )
        task_dir.mkdir(parents=True, exist_ok=True)
        spec = AgentSpec[type(args.input)](
            task_id=args.task_id,
            behaviour=self.role.behaviour,
            goal=args.goal,
            input=args.input,
            input_schema=self.role.input,
            answer_schema=self.role.answer,
            budget=self.role.budget,
        )
        (task_dir / "spec.json").write_text(spec.model_dump_json())
        task = bus.enqueue(task_dir, parent_agent=self.parent)
        return ctx.result(self.name, f"queued agent {task} for task {args.task_id} at {task_dir}")
