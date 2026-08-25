# Chooses which kind of process a task gets, by the input contract its role declares.
import collections.abc
import pathlib

from ancalagon.contracts.task_spec import TaskSpec
from ancalagon.fs.file_system import FileSystem
from ancalagon.supervisor.process import Process
from ancalagon.supervisor.spawner import Spawner


class SpawnByInput(Spawner):
    def __init__(
        self,
        default: Spawner,
        by_input: collections.abc.Mapping[str, Spawner],
        fs: FileSystem,
    ):
        self.default = default
        self.by_input = by_input
        self.fs = fs

    def spawn(self, task_dir: pathlib.PurePath, agent_id: int) -> Process:
        spec = TaskSpec.model_validate_json(self.fs.read_text(task_dir / "spec.json"))
        return self.by_input.get(spec.role.input.name, self.default).spawn(task_dir, agent_id)
