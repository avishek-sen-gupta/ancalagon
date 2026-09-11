# Queues one task for one role; the supervisor spawns it.
import pathlib

from ancalagon.bus.bus import Bus
from ancalagon.contracts.agent_ref import AgentRef
from ancalagon.contracts.agent_spec import AgentSpec
from ancalagon.contracts.no_agent_ref import NoAgentRef
from ancalagon.contracts.role import Role
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.fs.file_system import FileSystem
from ancalagon.schedule.active_for import active_for
from ancalagon.schedule.latest_event import latest_event
from ancalagon.tools.delegate.delegate_args import DelegateArgs
from ancalagon.tools.delegate.delegating import (
    delegate_args,
    delegate_description,
    delegate_name,
)
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext


class DelegateTo(Tool[DelegateArgs]):
    cost = 1

    def __init__(
        self,
        bus: Bus,
        role_name: str,
        role: Role,
        run_dir: pathlib.PurePath,
        parent: int,
        fs: FileSystem,
    ):
        self.bus = bus
        self.name = delegate_name(role_name)
        self.description = delegate_description(role_name, role)
        self.role = role
        self.run_dir = run_dir
        self.parent = parent
        self.fs = fs
        self.args_model = delegate_args(role_name, role)

    def run(self, args: DelegateArgs, ctx: ToolContext) -> ToolResult:
        task_dir = self.run_dir / "tasks" / args.task_id
        snapshot = self.bus.snapshot()
        active = active_for(snapshot, str(task_dir))
        if active:
            agent = active[0]
            status = latest_event(snapshot, agent).status
            return ctx.failure(
                self.name,
                f"task {args.task_id} is already {status.value} as agent {agent}",
            )
        self.fs.mkdir(task_dir, parents=True, exist_ok=True)
        spec = AgentSpec[type(args.input)](
            task_id=args.task_id, role=self.role, goal=args.goal, input=args.input
        )
        self.fs.write_text(task_dir / "spec.json", spec.model_dump_json())
        queued = self.bus.enqueue(task_dir, parent_agent=self.parent)
        return self._queued_result(queued, args.task_id, task_dir, ctx)

    def _queued_result(
        self,
        queued: AgentRef | NoAgentRef,
        task_id: str,
        task_dir: pathlib.PurePath,
        ctx: ToolContext,
    ) -> ToolResult:
        match queued:
            case AgentRef(id=agent_id):
                return ctx.result(
                    self.name, f"queued agent {agent_id} for task {task_id} at {task_dir}"
                )
            case NoAgentRef():
                return ctx.failure(self.name, f"no bus to queue task {task_id} at {task_dir}")
