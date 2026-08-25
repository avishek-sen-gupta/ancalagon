# Queues a watcher for a file, measuring how large it is now so the caller need not.
import pathlib

from ancalagon.bus.lifecycle_store import LifecycleStore
from ancalagon.clock.clock import Clock
from ancalagon.contracts.agent_spec import AgentSpec
from ancalagon.contracts.completed import Completed
from ancalagon.contracts.role import Role
from ancalagon.contracts.tool_result import ToolResult
from ancalagon.contracts.watch_request import WatchRequest
from ancalagon.contracts.watched import Watched
from ancalagon.fs.file_system import FileSystem
from ancalagon.schedule.active_for import active_for
from ancalagon.schedule.newest_agent import newest_agent
from ancalagon.tools.registry.tool import Tool
from ancalagon.tools.registry.tool_context import ToolContext
from ancalagon.tools.watch.watch_args import WatchArgs
from ancalagon.workspace.scope_error import ScopeError


def _size_in(outcome: str) -> int:
    reported = Completed[Watched].model_validate_json(outcome)
    return reported.value.size


class WatchFile(Tool[WatchArgs]):
    name = "watch_file"
    description = (
        "Wait for a file to grow. Queues a watcher that ends the moment the file is larger "
        "than it is right now, which wakes you once you idle. Its size is measured for you."
    )
    cost = 1
    args_model = WatchArgs

    def __init__(
        self, role: Role, run_dir: pathlib.PurePath, parent: int, clock: Clock, fs: FileSystem
    ):
        self.role = role
        self.run_dir = run_dir
        self.parent = parent
        self.clock = clock
        self.fs = fs

    def run(self, args: WatchArgs, ctx: ToolContext) -> ToolResult:
        try:
            watched = ctx.workspace.resolve_read(args.path)
        except ScopeError as exc:
            return ctx.failure(self.name, str(exc))
        return self._queued(args, watched, ctx)

    # What the caller has been told about is what the last watcher reported, never the file's
    # size now: measuring now would swallow every write that landed since it was last woken.
    def _reported(self, task_dir: pathlib.PurePath, bus: LifecycleStore) -> int:
        snapshot = bus.snapshot()
        if str(task_dir) not in {t.dir for t in snapshot.tasks}:
            return 0
        newest = newest_agent(snapshot, bus.task(task_dir).id)
        written = task_dir / f"outcome-{newest}.json"
        if not self.fs.exists(written):
            return 0
        return _size_in(self.fs.read_text(written))

    def _queued(self, args: WatchArgs, watched: pathlib.PurePath, ctx: ToolContext) -> ToolResult:
        task_dir = self.run_dir / "tasks" / args.task_id
        bus = LifecycleStore.open(self.run_dir / "bus.db", self.clock, self.fs)
        active = active_for(bus.snapshot(), str(task_dir))
        if active:
            return ctx.failure(self.name, f"task {args.task_id} is already running as {active[0]}")
        seen = self._reported(task_dir, bus)
        self.fs.mkdir(task_dir, parents=True, exist_ok=True)
        spec = AgentSpec[WatchRequest](
            task_id=args.task_id,
            role=self.role,
            goal=f"Wait until {watched} grows beyond {seen} bytes.",
            input=WatchRequest(path=str(watched), seen_bytes=seen),
        )
        self.fs.write_text(task_dir / "spec.json", spec.model_dump_json())
        agent = bus.enqueue(task_dir, parent_agent=self.parent)
        return ctx.result(self.name, f"queued agent {agent} watching {watched} from {seen} bytes")
