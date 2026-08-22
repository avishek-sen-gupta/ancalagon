# Queues one task for one role; the supervisor spawns it.
import pathlib

import pydantic

from ancalagon.bus.lifecycle_store import LifecycleStore
from ancalagon.clock.clock import Clock
from ancalagon.contracts.agent_spec import AgentSpec
from ancalagon.contracts.resolve import resolve_class
from ancalagon.contracts.role import Role
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.fs.file_system import FileSystem
from ancalagon.schedule.active_for import active_for
from ancalagon.tools.delegate.delegate_args import DelegateArgs
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext


class DelegateTo(Tool[DelegateArgs]):
    cost = 1

    def __init__(
        self,
        role_name: str,
        role: Role,
        run_dir: pathlib.Path,
        parent: int,
        clock: Clock,
        fs: FileSystem,
    ):
        self.name = f"delegate_{role_name}"
        self.description = (
            f"Queue a {role_name} task. Returns its task id immediately without waiting. "
            f"That agent is told: {role.behaviour} "
            "Reusing a task_id after that task has finished retries it, and the new agent "
            "inherits the previous one's transcript. Use a new task_id for a clean start."
        )
        self.role = role
        self.run_dir = run_dir
        self.parent = parent
        self.clock = clock
        self.fs = fs
        self.args_model = pydantic.create_model(
            f"DelegateTo{role_name.title().replace('_', '')}Args",
            __base__=DelegateArgs,
            input=(resolve_class(role.input), ...),
        )

    def run(self, args: DelegateArgs, ctx: ToolContext) -> ToolResult:
        task_dir = self.run_dir / "tasks" / args.task_id
        bus = LifecycleStore.open(self.run_dir / "bus.db", self.clock, self.fs)
        snapshot = bus.snapshot()
        active = active_for(snapshot, str(task_dir))
        if active:
            agent = active[0]
            status = max(snapshot.events[agent], key=lambda event: event.id).status
            return ctx.failure(
                self.name,
                f"task {args.task_id} is already {status.value} as agent {agent}",
            )
        self.fs.mkdir(task_dir, parents=True, exist_ok=True)
        spec = AgentSpec[type(args.input)](
            task_id=args.task_id, role=self.role, goal=args.goal, input=args.input
        )
        self.fs.write_text(task_dir / "spec.json", spec.model_dump_json())
        task = bus.enqueue(task_dir, parent_agent=self.parent)
        return ctx.result(self.name, f"queued agent {task} for task {args.task_id} at {task_dir}")
