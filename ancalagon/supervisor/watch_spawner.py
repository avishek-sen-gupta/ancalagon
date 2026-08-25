# Spawns the file watcher instead of a worker, for a task whose child does not need a model.
import pathlib
import subprocess
import sys

from ancalagon.env.environment import Environment
from ancalagon.fs.file_system import FileSystem
from ancalagon.sandbox.sandbox import Sandbox
from ancalagon.supervisor.process import Process
from ancalagon.supervisor.spawner import Spawner
from ancalagon.supervisor.subprocess_spawner import inherited


class WatchSpawner(Spawner):
    def __init__(
        self,
        run_dir: pathlib.PurePath,
        config_path: pathlib.PurePath,
        environment: Environment,
        fs: FileSystem,
        sandbox: Sandbox,
    ):
        self.run_dir = run_dir
        self.config_path = config_path
        self.environment = environment
        self.fs = fs
        self.sandbox = sandbox

    def spawn(self, task_dir: pathlib.PurePath, agent_id: int) -> Process:
        stderr = task_dir / f"stderr-{agent_id}.log"
        self.fs.mkdir(stderr.parent, parents=True, exist_ok=True)
        command = [
            sys.executable,
            "-m",
            "ancalagon.watch.watch",
            "--run-dir",
            str(self.run_dir),
            "--dir",
            str(task_dir),
            "--agent-id",
            str(agent_id),
            "--config",
            str(self.config_path),
        ]
        return subprocess.Popen(
            list(self.sandbox.wrap(command)),
            stdout=subprocess.DEVNULL,
            stderr=self.fs.open_write(stderr),
            cwd=self.run_dir,
            env=inherited(self.environment, self.sandbox),
        )
