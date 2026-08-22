# Indirection for process creation, so tests can supervise without launching interpreters.
import pathlib
import typing

from ancalagon.supervisor.process import Process


class Spawner(typing.Protocol):
    def spawn(self, task_dir: pathlib.PurePath, agent_id: int) -> Process: ...
