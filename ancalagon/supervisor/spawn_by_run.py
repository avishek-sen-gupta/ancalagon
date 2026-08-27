# Chooses which kind of process a task gets: a role that names a run function is served
# by one, and every other role by a session.
import pathlib

from ancalagon.contracts.no_run import NO_RUN
from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.fs.file_system import FileSystem
from ancalagon.supervisor.process import Process
from ancalagon.supervisor.spawner import Spawner


class SpawnByRun(Spawner):
    def __init__(self, default: Spawner, deterministic: Spawner, fs: FileSystem):
        self.default = default
        self.deterministic = deterministic
        self.fs = fs

    def spawn(self, task_dir: pathlib.PurePath, agent_id: int) -> Process:
        spec = TaskSpec.model_validate_json(self.fs.read_text(task_dir / "spec.json"))
        chosen = self.default if spec.role.run == NO_RUN else self.deterministic
        return chosen.spawn(task_dir, agent_id)
